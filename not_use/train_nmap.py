import torch
import argparse
import os
import os.path as osp
from tqdm import tqdm
from core.data import train_nmap_loader, val_nmap_loader
from not_use.nmap_network import NMap_AE, NMap_ResnetAE

parser = argparse.ArgumentParser(description='train')
parser.add_argument('--data_path', default="/mnt/home_6T/public/jayliu0313/datasets/Eyecandies/", type=str)
parser.add_argument('--ckpt_path', default="./checkpoints/Nmap_ResnetAE_wonoise")
parser.add_argument('--batch_size', default=64, type=int)
parser.add_argument('--image_size', default=224, type=int)

# Training Setup
parser.add_argument("--load_ckpt", default=None)
parser.add_argument("--learning_rate", default=0.0003)
parser.add_argument('--weight_decay', type=float, default=0.05, help='weight decay (default: 0.05)')
parser.add_argument("--workers", default=4)
parser.add_argument("--epochs", default=1000)
parser.add_argument('--CUDA', type=int, default=0, help="choose the device of CUDA")

# Contrstive Learning
# parser.add_argument("--contrastive_w", default=0.001)
# parser.add_argument("--temperature_f", default=0.5)
# parser.add_argument("--temperature_l", default=1.0)

args = parser.parse_args()
cuda_idx = str(args.CUDA)
os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"]= cuda_idx

data_loader = train_nmap_loader(args)
val_loader = val_nmap_loader(args)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

print("current device:", device)

if not os.path.exists(args.ckpt_path):
    os.makedirs(args.ckpt_path)

# contrastive = Contrastive(args)

class Train_Nmap():
    def __init__(self, args):
        self.train_log_file = open(osp.join(args.ckpt_path, "training_log.txt"), "a", 1)
        self.val_log_file = open(osp.join(args.ckpt_path, "val_log.txt"), "a", 1)
        self.best_val_loss = float('inf')
        self.epochs = args.epochs
        self.epoch = 0
        self.image_size = args.image_size
        self.total_loss = 0.0
        self.val_every = 5  # every 5 epoch to check validation

        self.model = NMap_ResnetAE(device)
        self.model.to(device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=args.learning_rate)
        self.criterion = torch.nn.MSELoss().to(device)
        if args.load_ckpt is not None:
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
    
    def training(self):
        for self.epoch in range(self.epochs):
            epoch_loss = 0.0
            for nmap in tqdm(data_loader, desc=f'Training Epoch: {self.epoch}'):
                self.optimizer.zero_grad()

                nmap = nmap.to(device)
                out = self.model(nmap)
                loss = self.criterion(nmap, out)
                loss.backward()
                
                self.optimizer.step()
                epoch_loss += loss.item()
                
            epoch_loss /= len(data_loader)
            self.total_loss += epoch_loss
            
            print('Epoch {}: Loss: {:.6f}'.format(self.epoch, epoch_loss))

            if self.epoch % self.val_every == 0 or self.epoch == self.epochs - 1:
                self.model.eval()
                epoch_val_loss = 0.0
                with torch.no_grad():
                    for nmap in val_loader:
                        nmap = nmap.to(device)
                        out = self.model(nmap)
                        loss = self.criterion(nmap, out)
                    
                        epoch_val_loss += loss.item()

                epoch_val_loss = epoch_val_loss / len(val_loader)

                if epoch_val_loss < self.best_val_loss:
                    self.best_val_loss = epoch_val_loss
                    self.save_ckpt(self.best_val_loss, "best_ckpt.pth")
                    print("Save the best checkpoint")
                
                print(f"Epoch [{self.epoch}/{self.epochs}] - " f"Valid Loss: {epoch_val_loss:.6f}")
                self.val_log_file.write('Epoch {}: Loss: {:.6f}\n'.format(self.epoch, epoch_val_loss))

            self.train_log_file.write('Epoch {}: Loss: {:.6f}\n'.format(self.epoch, epoch_loss))

        self.save_ckpt(epoch_loss, "last_ckpt.pth")
        self.train_log_file.close()
        self.val_log_file.close()
    
if __name__ == '__main__':
    runner = Train_Nmap(args)
    runner.training()


# class Train_Nmap_EfficientAE():
#     def __init__(self, args):
#         self.train_log_file = open(osp.join(args.ckpt_path, "training_log.txt"), "a", 1)
#         self.val_log_file = open(osp.join(args.ckpt_path, "val_log.txt"), "a", 1)
#         self.best_val_loss = float('inf')
#         self.epochs = args.epochs
#         self.epoch = 0
#         self.image_size = args.image_size
#         self.total_loss = 0.0
#         self.val_every = 5  # every 5 epoch to check validation
#         self.rgb_model = RGB_Model(device)
#         self.model = NMap_Repair_Feat_AE(device)
#         self.model.to(device)
#         self.optimizer = torch.optim.Adam(self.model.parameters(), lr=args.learning_rate)
#         self.criterion = torch.nn.MSELoss().to(device)
#         if args.load_ckpt is not None:
#             self.load_ckpt()
    
#     def save_ckpt(self, curr_loss, filename):
#         state_dict = {
#             'model': self.model.state_dict(),
#             'current_iteration': self.epoch,
#             'optimizer_state_dict': self.optimizer.state_dict(),
#             'epoch_loss': curr_loss,
#         }
#         torch.save(state_dict, os.path.join(args.ckpt_path, filename))

#     def load_ckpt(self):
#         checkpoint = torch.load(args.load_ckpt)
#         self.model.load_state_dict(checkpoint['model'])
#         self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
#         self.epoch = checkpoint['current_iteration']
    
#     def training(self):
#         for self.epoch in range(self.epochs):
#             epoch_loss = 0.0
#             epoch_rec_loss = 0.0
#             epoch_feat_loss = 0.0
#             for nmap in tqdm(data_loader, desc=f'Training Epoch: {self.epoch}'):
#                 self.optimizer.zero_grad()

#                 nmap = nmap.to(device)
#                 out, feat_loss = self.model(nmap)
#                 rec_loss = self.criterion(nmap, out)
#                 loss = rec_loss + feat_loss 
#                 loss.backward()
#                 # print("feat:", feat_loss)
#                 # print("rec:", rec_loss)
#                 self.optimizer.step()
                
#                 epoch_loss += loss.item()
#                 epoch_rec_loss += rec_loss.item() 
#                 epoch_feat_loss += feat_loss.item()
            
                
#             epoch_loss /= len(data_loader)
#             epoch_rec_loss /= len(data_loader)
#             epoch_feat_loss /= len(data_loader)
#             self.total_loss += epoch_loss
            
#             print('Epoch {}: Loss: {:.6f}, Rec Loss: {:.6f}, Feat Loss: {:.6f}'.format(self.epoch, epoch_loss, epoch_rec_loss, epoch_feat_loss))

#             if self.epoch % self.val_every == 0 or self.epoch == self.epochs - 1:
#                 self.model.eval()
#                 epoch_val_loss = 0.0
#                 epoch_val_rec_loss = 0.0
#                 epoch_val_feat_loss = 0.0
#                 with torch.no_grad():
#                     for nmap in val_loader:
#                         nmap = nmap.to(device)
#                         out, feat_loss = self.model(nmap)
#                         rec_loss = self.criterion(nmap, out)
#                         loss = rec_loss + feat_loss
                        
#                         epoch_val_loss += loss.item()
#                         epoch_val_rec_loss += rec_loss.item() 
#                         epoch_val_feat_loss += feat_loss.item()

#                 epoch_val_rec_loss /= len(val_loader)
#                 epoch_val_feat_loss /= len(val_loader)
#                 epoch_val_loss /= len(val_loader)

#                 if epoch_val_loss < self.best_val_loss:
#                     self.best_val_loss = epoch_val_loss
#                     self.save_ckpt(self.best_val_loss, "best_ckpt.pth")
#                     print("Save the best checkpoint")
                
#                 print(f"Epoch [{self.epoch}/{self.epochs}] - " f"Validation Loss: {epoch_val_loss:.6f}, Rec Loss: {epoch_val_rec_loss:.6f}, Feat Loss: {epoch_val_feat_loss:.6f}")
#                 self.val_log_file.write('Epoch {}: Loss: {:.6f}, Rec Loss: {:.6f}, Feat Loss: {:.6f}\n'.format(self.epoch, epoch_val_loss, epoch_val_rec_loss, epoch_val_feat_loss))

#             self.train_log_file.write('Epoch {}: Loss: {:.6f}, Rec Loss: {:.6f}, Feat Loss: {:.6f}\n'.format(self.epoch, epoch_loss, epoch_rec_loss, epoch_feat_loss))

#         self.save_ckpt(epoch_loss, "last_ckpt.pth")
#         self.train_log_file.close()
#         self.val_log_file.close()