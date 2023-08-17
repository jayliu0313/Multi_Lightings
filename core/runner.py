from core.data import test_lightings_loader
from core.reconstruct import Mean_Reconstruct, Reconstruct, Normal_Reconstruct
import torch
import os
import os.path as osp

class Runner():
    def __init__(self, args, model, cls):
        cls_path = os.path.join(args.output_dir, cls)
        if not os.path.exists(cls_path):
            os.makedirs(cls_path)

        self.args = args
        if args.method_name == "mean_rec":
            self.method = Mean_Reconstruct(args, model, cls_path)
        elif args.method_name == "rec":
            self.method = Reconstruct(args, model, cls_path)
        elif args.method_name == "nmap_rec":
            self.method = Normal_Reconstruct(args, model, cls_path)
        else:
            return TypeError
        self.cls = cls
        self.log_file = open(osp.join(cls_path, "class_score.txt"), "a", 1)
        self.method_name = args.method_name
        
    def evaluate(self):
        dataloader = test_lightings_loader(self.args, self.cls)
        with torch.no_grad():
            for i, ((images, normal), gt, label) in enumerate(dataloader):
                if self.method_name == "nmap_rec":
                    self.method.predict(i, normal, gt, label)
                else:
                    self.method.predict(i, images, gt, label)

        image_rocauc, pixel_rocauc, au_pro = self.method.calculate_metrics()
        total_rec_loss = self.method.get_rec_loss()
        rec_mean_loss = total_rec_loss / len(dataloader)

        self.method.visualizae_heatmap()

        image_rocaucs = dict()
        pixel_rocaucs = dict()
        au_pros = dict()
        rec_losses = dict()
        image_rocaucs[self.method_name] = round(image_rocauc, 3)
        pixel_rocaucs[self.method_name] = round(pixel_rocauc, 3)
        au_pros[self.method_name] = round(au_pro, 3)
        rec_losses[self.method_name] = round(rec_mean_loss, 6)

        self.log_file.write(
            f'Class: {self.cls} {self.method_name}, Image ROCAUC: {image_rocauc:.3f}, Pixel ROCAUC: {pixel_rocauc:.3f}, AUPRO:  {au_pro:.3f}\n'
            f'Reconstruction Loss: {rec_mean_loss}'
        )
        self.log_file.close()
        return image_rocaucs, pixel_rocaucs, au_pros, rec_losses
