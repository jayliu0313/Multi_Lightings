import torch
import argparse
import os
import os.path as osp
from tqdm import tqdm
from core.data import train_lightings_loader, val_lightings_loader
from core.models.fusion_network import FeatureFusion
from core.models.nmap_network import NMap_AE
from core.models.rgb_network import Convolution_AE
from core.models.contrastive import Contrastive

parser = argparse.ArgumentParser(description='train')
parser.add_argument('--data_path', default="/mnt/home_6T/public/jayliu0313/datasets/Eyecandies/", type=str)
parser.add_argument('--ckpt_path', default="./checkpoints/fusion_model")
parser.add_argument('--batch_size', default=16, type=int)
parser.add_argument('--image_size', default=224, type=int)

# Training Setup
parser.add_argument("--load_rgb_ckpt", default="checkpoints/cnn_fuseRec_finetune/best_ckpt.pth")
parser.add_argument("--load_nmap_ckpt", default="checkpoints/Nmap_Rec/best_ckpt.pth")
parser.add_argument("--load_fuse_ckpt", default=None)
parser.add_argument("--learning_rate", default=0.0003)
parser.add_argument("--workers", default=4)
parser.add_argument("--epochs", default=700)
parser.add_argument('--CUDA', type=int, default=0, help="choose the device of CUDA")

# Contrstive Learning
parser.add_argument("--contrastive_w", default=1)
parser.add_argument("--temperature_f", default=0.5)
parser.add_argument("--temperature_l", default=1.0)

args = parser.parse_args()
cuda_idx = str(args.CUDA)
os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"]= cuda_idx

data_loader = train_lightings_loader(args)
val_loader = val_lightings_loader(args)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

print("current device:", device)

if not os.path.exists(args.ckpt_path):
    os.makedirs(args.ckpt_path)

# contrastive = Contrastive(args)

class Train_Fusion():
    def __init__(self, args):
        self.train_log_file = open(osp.join(args.ckpt_path, "training_log.txt"), "a", 1)
        self.val_log_file = open(osp.join(args.ckpt_path, "val_log.txt"), "a", 1)
        self.best_val_loss = float('inf')
        self.epochs = args.epochs
        self.epoch = 0
        self.img_size = args.image_size
        self.total_loss = 0.0
        self.val_every = 5  # every 5 epoch to check validation
        # load rgb extractor
        self.rgb_extract = Convolution_AE(device).to(device)
        checkpoint = torch.load(args.load_rgb_ckpt)
        self.rgb_extract.load_state_dict(checkpoint['model'])
        self.rgb_extract.freeze_model()

         # load nmap extractor
        self.nmap_extract = NMap_AE(device).to(device)
        checkpoint = torch.load(args.load_nmap_ckpt)
        self.nmap_extract.load_state_dict(checkpoint['model'])
        self.nmap_extract.freeze_model()

        self.model = FeatureFusion(args, 256, 256, device)
        self.model.to(device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=args.learning_rate)

        self.contrastive = Contrastive(args)

        self.features = []

        if args.load_fuse_ckpt is not None:
            self.load_ckpt()
    
    def save_ckpt(self, curr_loss, filename):
        state_dict = {
            'model': self.model.state_dict(),
            'current_iteration': self.epoch,
            'optimizer_state_dict': self.optimizer.state_dict(),
            'epoch_loss': curr_loss,
        }
        torch.save(state_dict, os.path.join(args.ckpt_path, filename))

    def load_ckpt(self):
        checkpoint = torch.load(args.load_ckpt)
        self.model.load_state_dict(checkpoint['model'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.epoch = checkpoint['current_iteration']
    
    def extract_feature(self, lightings, nmap):
        with torch.no_grad():
            lightings = lightings.reshape(-1, 3, self.img_size, self.img_size) 
            six_fc = self.rgb_extract.get_fc(lightings)
            rgb_feature = self.rgb_extract.get_mean_fc(six_fc)
            nmap_feature = self.nmap_extract.encode(nmap)
        return rgb_feature, nmap_feature

    def training(self):
        for self.epoch in range(self.epochs):
            epoch_loss = 0.0
            for lightings, nmap in tqdm(data_loader, desc=f'Training Epoch: {self.epoch}'):
                self.optimizer.zero_grad()

                rgb_feature, nmap_feature = self.extract_feature(lightings, nmap)
                # rgb_feature, nmap_feature = self.model(rgb_feature.to(device), nmap_feature.to(device))
                loss = self.contrastive.loss(rgb_feature.to(device), nmap_feature.to(device))
                print(loss.item())
        #         loss.backward()
                
        #         self.optimizer.step()
        #         epoch_loss += loss.item()
                
        #     epoch_loss /= len(data_loader)
        #     self.total_loss += epoch_loss
            
        #     print('Epoch {}: Loss: {:.6f}'.format(self.epoch, epoch_loss))

        #     if self.epoch % self.val_every == 0 or self.epoch == self.epochs - 1:
        #         self.model.eval()
        #         epoch_val_loss = 0.0
        #         with torch.no_grad():
        #             for lightings, nmap in val_loader:
        #                 rgb_feature, nmap_feature = self.extract_feature(lightings.to(device), nmap.to(device))
        #                 rgb_feature, nmap_feature = self.model(rgb_feature.to(device), nmap_feature.to(device))
        #                 loss = self.contrastive.loss(rgb_feature, nmap_feature)
        #                 epoch_val_loss += loss.item()

        #         epoch_val_loss = epoch_val_loss / len(val_loader)

        #         if epoch_val_loss < self.best_val_loss:
        #             self.best_val_loss = epoch_val_loss
        #             self.save_ckpt(self.best_val_loss, "best_ckpt.pth")
        #             print("Save the best checkpoint")
                
        #         print(f"Epoch [{self.epoch}/{self.epochs}] - " f"Valid Loss: {epoch_val_loss:.6f}")
        #         self.val_log_file.write('Epoch {}: Loss: {:.6f}\n'.format(self.epoch, epoch_val_loss))

        #     self.train_log_file.write('Epoch {}: Loss: {:.6f}\n'.format(self.epoch, epoch_loss))

        # self.save_ckpt(epoch_loss, "last_ckpt.pth")
        # self.train_log_file.close()
        # self.val_log_file.close()
    


if __name__ == '__main__':
    runner = Train_Fusion(args)
    runner.training()