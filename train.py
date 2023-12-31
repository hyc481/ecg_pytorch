import os
import os.path as osp
import json

from network import ecgNet
from dataset import EcgDataset1D

import numpy as np
import torch
from torch import nn
from torch.utils.tensorboard import SummaryWriter
# from torch.optim.lr_scheduler import ReduceLROnPlateau
from tqdm import tqdm
import argparse

from utils import load_checkpoint, save_checkpoint

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    return parser.parse_args()

class ecgTrainer:
    def __init__(self, **params):
        self.config = params

        self.exp_name = params['exp_name']
        self.log_dir = osp.join(params["exp_dir"], self.exp_name, "logs")
        self.pth_dir = osp.join(params["exp_dir"], self.exp_name, "checkpoints")

        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.pth_dir, exist_ok=True)

        self.writer = SummaryWriter(log_dir=self.log_dir)
        self.model = self._init_net()
        self.optimizer = self._init_optimizer()
        self.criterion = nn.CrossEntropyLoss().to(self.config["device"])

        self.train_loader, self.val_loader = self._init_dataloaders()

        pretrained_path = self.config.get("model_path", False)
        if pretrained_path:
            self.training_epoch, self.total_iter = load_checkpoint(
                pretrained_path, self.model, optimizer=self.optimizer,
            )

        else:
            self.training_epoch = 0
            self.total_iter = 0

        self.epochs = self.config["epochs"]

    def _init_net(self):
        model = ecgNet(**self.config)
        return model

    def _init_optimizer(self):
        """
            optimizer = torch.optim.SGD(self.model.parameters(), lr=0.001, momentum=0.9)
            return optimizer
        """
        optimizer = torch.optim.Adam(
            self.model.parameters(), self.config["lr"]
        )
        return optimizer

    def _init_dataloaders(self):
        train_loader = EcgDataset1D(
            self.config["train_json"], self.config["mapping_json"],
        ).get_dataloader(
            batch_size=self.config["batch_size"],
            num_workers=self.config["num_workers"],
        )
        val_loader = EcgDataset1D(
            self.config["val_json"], self.config["mapping_json"],
        ).get_dataloader(
            batch_size=self.config["batch_size"],
            num_workers=self.config["num_workers"],
        )

        return train_loader, val_loader

    def train_epoch(self):
        self.model.train()
        total_loss = 0

        gt_class = np.empty(0)
        pd_class = np.empty(0)

        for i, batch in enumerate(self.train_loader):
            inputs = batch["image"].to(self.config["device"])
            targets = batch["class"].to(self.config["device"])
            predictions = self.model(inputs)
            loss = self.criterion(predictions, targets)

            classes = predictions.topk(k=1)[1].view(-1).cpu().numpy()

            gt_class = np.concatenate((gt_class, batch["class"].numpy()))
            pd_class = np.concatenate((pd_class, classes))

            total_loss += loss.item()

            self.optimizer.zero_grad()
            loss.backward()
            self.optimizer.step()

            if (i + 1) % 100 == 0:
                print(
                    "\tIter [%d/%d] Loss: %.4f"
                    % (i + 1, len(self.train_loader), loss.item()),
                )

            self.writer.add_scalar(
                "Train loss (iterations)", loss.item(), self.total_iter,
            )
            self.total_iter += 1

        total_loss /= len(self.train_loader)
        class_accuracy = sum(pd_class == gt_class) / pd_class.shape[0]

        print("Train loss - {:4f}".format(total_loss))
        print("Train CLASS accuracy - {:4f}".format(class_accuracy))

        self.writer.add_scalar("Train loss (epochs)", total_loss, self.training_epoch)
        self.writer.add_scalar(
            "Train CLASS accuracy", class_accuracy, self.training_epoch,
        )

    def val(self):
        self.model.eval()
        total_loss = 0

        gt_class = np.empty(0)
        pd_class = np.empty(0)

        with torch.no_grad():
            for i, batch in tqdm(enumerate(self.val_loader)):
                inputs = batch["image"].to(self.config["device"])
                targets = batch["class"].to(self.config["device"])
                predictions = self.model(inputs)
                loss = self.criterion(predictions, targets)

                classes = predictions.topk(k=1)[1].view(-1).cpu().numpy()

                gt_class = np.concatenate((gt_class, batch["class"].numpy()))
                pd_class = np.concatenate((pd_class, classes))

                total_loss += loss.item()

        total_loss /= len(self.val_loader)
        class_accuracy = sum(pd_class == gt_class) / pd_class.shape[0]

        print("Validation loss - {:4f}".format(total_loss))
        print("Validation CLASS accuracy - {:4f}".format(class_accuracy))

        self.writer.add_scalar("Validation loss", total_loss, self.training_epoch)
        self.writer.add_scalar(
            "Validation CLASS accuracy", class_accuracy, self.training_epoch,
        )

        return total_loss

    def loop(self):
        # scheduler = ReduceLROnPlateau(self.optimizer, 'min')
        for epoch in range(self.training_epoch, self.epochs):
            print("Epoch - {}".format(self.training_epoch + 1))
            self.train_epoch()
            save_checkpoint(
                {
                    "state_dict": self.model.state_dict(),
                    "optimizer": self.optimizer.state_dict(),
                    "epoch": epoch,
                    "total_iter": self.total_iter,
                },
                osp.join(self.pth_dir, "{:0>8}.pth".format(epoch)),
            )

            val_loss = self.val()
            # scheduler.step(val_loss)

            self.training_epoch += 1


if __name__ == "__main__":
    args = parse_args()
    config = json.loads(open(args.config).read())
    trainer = ecgTrainer(**config)
    print('import finished')
    trainer.loop()

