import os
import glob
from PIL import Image
from torchvision import transforms
import glob
from torch.utils.data import Dataset
from utils.mvtec3d_util import *
from torch.utils.data import DataLoader
import numpy as np
import math

def eyecandies_classes():
    return [
        'CandyCane',
        'ChocolateCookie',
        'ChocolatePraline',
        'Confetto',
        'GummyBear',
        'HazelnutTruffle',
        'LicoriceSandwich',
        'Lollipop',
        'Marshmallow',
        'PeppermintCandy',   
    ]

def mvtec3d_classes():
    return [
        "bagel",
        "cable_gland",
        "carrot",
        "cookie",
        "dowel",
        "foam",
        "peach",
        "potato",
        "rope",
        "tire",
    ]

def gauss_noise_tensor(img):
    assert isinstance(img, torch.Tensor)
    dtype = img.dtype
    if not img.is_floating_point():
        img = img.to(torch.float32)
    
    sigma = 0.1
    
    out = img + sigma * torch.randn_like(img)
    
    if out.dtype != dtype:
        out = out.to(dtype)
        
    return out

MEAN = [0.0, 0.0, 0.0]
STD = [255, 255, 255]

class BaseDataset(Dataset):

    def __init__(self, split, class_name, img_size, dataset_path='datasets/eyecandies_preprocessed'):
       
        self.cls = class_name
        self.size = img_size
        self.img_path = os.path.join(dataset_path, self.cls, split)
        self.rgb_transform = transforms.Compose(
            [transforms.Resize((img_size, img_size), interpolation=transforms.InterpolationMode.BICUBIC),
             transforms.ToTensor()])    

class TestLightings(BaseDataset):
    def __init__(self, class_name, img_size, dataset_path='datasets/eyecandies_preprocessed'):
        super().__init__(split="test_public", class_name=class_name, img_size=img_size, dataset_path=dataset_path)
        self.gt_transform = transforms.Compose([
            transforms.Resize((img_size, img_size), interpolation=transforms.InterpolationMode.NEAREST),
            transforms.ToTensor()])
        self.data_paths, self.gt_paths = self.load_dataset()  # self.labels => good : 0, anomaly : 1

    def load_dataset(self):
        data_tot_paths = []
        gt_tot_paths = []

        rgb_paths = glob.glob(os.path.join(self.img_path, 'data') + "/*_image_*.png")
        normal_paths = glob.glob(os.path.join(self.img_path, 'data') + "/*_normals.png")
        depth_paths = glob.glob(os.path.join(self.img_path, 'data') + "/*_depth.png")
        gt_paths = [os.path.join(self.img_path, 'data', str(i).zfill(2)+'_mask.png') for i in range(len(depth_paths))]
        
        rgb_paths.sort()
        normal_paths.sort()
        depth_paths.sort()
        gt_paths.sort()
        
        rgb_lighting_paths = []
        rgb_6_paths = []
        for i in range(len(rgb_paths)):
            rgb_6_paths.append(rgb_paths[i])
            if (i + 1) % 6 == 0:
                rgb_lighting_paths.append(rgb_6_paths)
                rgb_6_paths = []

        sample_paths = list(zip(rgb_lighting_paths, normal_paths, depth_paths))
        data_tot_paths.extend(sample_paths)
        gt_tot_paths.extend(gt_paths)
        
        return data_tot_paths, gt_tot_paths

    def __len__(self):
        return len(self.data_paths)

    def __getitem__(self, idx):
        img_path, gt = self.data_paths[idx], self.gt_paths[idx]
        rgb_path = img_path[0]
        normal_path = img_path[1]

        normal = Image.open(normal_path).convert('RGB')
        normal = self.rgb_transform(normal)
        images = []
        for i in range(6):
            img = Image.open(rgb_path[i]).convert('RGB')
            
            img = self.rgb_transform(img)
            # img = img * mask
            images.append(img)
        images = torch.stack(images)

        gt = Image.open(gt).convert('L')
        if np.any(gt):
            gt = self.gt_transform(gt)
            gt = torch.where(gt > 0.5, 1., .0)
            label = 1
        else:
            gt = self.gt_transform(gt)
            gt = torch.where(gt > 0.5, 1., .0)
            label = 0

        return (images, normal), gt[:1], label

class TrainLightings(Dataset):
    def __init__(self, img_size=224, dataset_path='datasets/eyecandies_preprocessed', train_type="normal_only"):
        self.size = img_size
        self.rgb_transform = transforms.Compose(
        [transforms.Resize((self.size, self.size), interpolation=transforms.InterpolationMode.BICUBIC),
         transforms.ToTensor(),
        ])
        self.train_type = train_type
        self.img_path = dataset_path
        self.data_paths, self.labels = self.load_dataset()  # self.labels => good : 0, anomaly : 1

    def load_dataset(self):
        data_tot_paths = []
        tot_labels = []
        rgb_paths = []
        depth_paths = []
        normal_paths = []

        for cls in eyecandies_classes():
            if self.train_type == "normal_only":
                normal_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'train', 'data') + "/*_normals.png"))
                depth_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'train', 'data') + "/*_depth.png"))
            else:
                rgb_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'train', 'data', "*_image_*.png")))
                normal_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'train', 'data') + "/*_normals.png"))
                depth_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'train', 'data') + "/*_depth.png"))
        
        rgb_paths.sort()
        normal_paths.sort()     
        depth_paths.sort()
     
        if self.train_type == "normal_only":
            sample_paths = list(zip(normal_paths, depth_paths))
        else:
            rgb_lighting_paths = []
            rgb_6_paths = []
            
            for i in range(len(rgb_paths)):
                rgb_6_paths.append(rgb_paths[i])
                if (i + 1) % 6 == 0:
                    rgb_lighting_paths.append(rgb_6_paths)
                    rgb_6_paths = []
            sample_paths = list(zip(rgb_lighting_paths, normal_paths, depth_paths))
        
        data_tot_paths.extend(sample_paths)
        tot_labels.extend([0] * len(sample_paths))
        return data_tot_paths, tot_labels

    def __len__(self):
        return len(self.data_paths)

    def __getitem__(self, idx):
        img_path, label = self.data_paths[idx], self.labels[idx]

        if self.train_type == "normal_only":
            normal_path = img_path[0]
            depth_path = img_path[1]
            normal = Image.open(normal_path).convert('RGB')
            normal = self.rgb_transform(normal)
            return normal
        
        else:
            rgb_path = img_path[0]
            images = []
            for i in range(6):
                img = Image.open(rgb_path[i]).convert('RGB')
                img = self.rgb_transform(img)
                images.append(img)
            images = torch.stack(images)

            normal_path = img_path[1]
            depth_path = img_path[2]
            normal = Image.open(normal_path).convert('RGB')
            nmap = self.rgb_transform(normal)
            return images, nmap

class ValLightings(Dataset):
    def __init__(self, img_size=224, dataset_path='datasets/eyecandies', val_type=""):
        self.size = img_size
        self.rgb_transform = transforms.Compose(
        [transforms.Resize((self.size, self.size), interpolation=transforms.InterpolationMode.BICUBIC),
         transforms.ToTensor(),
        ])
        self.val_type = val_type
        self.img_path = dataset_path
        self.data_paths, self.labels = self.load_dataset()  # self.labels => good : 0, anomaly : 1

    def load_dataset(self):
        data_tot_paths = []
        tot_labels = []
        rgb_paths = []
        depth_paths = []
        normal_paths = []

        for cls in eyecandies_classes():
            if self.val_type == "normal_only":
                normal_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'val', 'data') + "/*_normals.png"))
                depth_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'val', 'data') + "/*_depth.png"))
            else:
                rgb_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'val', 'data', "*_image_*.png")))
                normal_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'val', 'data') + "/*_normals.png"))
                depth_paths.extend(glob.glob(os.path.join(self.img_path, cls, 'val', 'data') + "/*_depth.png"))
        
        rgb_paths.sort()
        normal_paths.sort()     
        depth_paths.sort()
     
        if self.val_type == "normal_only":
            sample_paths = list(zip(normal_paths, depth_paths))
        else:
            rgb_lighting_paths = []
            rgb_6_paths = []
            
            for i in range(len(rgb_paths)):
                rgb_6_paths.append(rgb_paths[i])
                if (i + 1) % 6 == 0:
                    rgb_lighting_paths.append(rgb_6_paths)
                    rgb_6_paths = []
            sample_paths = list(zip(rgb_lighting_paths, normal_paths, depth_paths))
        
        data_tot_paths.extend(sample_paths)
        tot_labels.extend([0] * len(sample_paths))
        return data_tot_paths, tot_labels

    def __len__(self):
        return len(self.data_paths)

    def __getitem__(self, idx):
        img_path, label = self.data_paths[idx], self.labels[idx]

        if self.val_type == "normal_only":
            normal_path = img_path[0]
            depth_path = img_path[1]
            normal = Image.open(normal_path).convert('RGB')
            nmap = self.rgb_transform(normal)
            return nmap
        
        else:
            rgb_path = img_path[0]
            images = []
            for i in range(6):
                img = Image.open(rgb_path[i]).convert('RGB')
                img = self.rgb_transform(img)
                images.append(img)
            images = torch.stack(images)

            normal_path = img_path[1]
            depth_path = img_path[2]
            normal = Image.open(normal_path).convert('RGB')
            nmap = self.rgb_transform(normal)
            return images, nmap

def test_lightings_loader(args, cls):
    dataset = TestLightings(cls, args.image_size, args.data_path)
    data_loader = DataLoader(dataset=dataset, batch_size=args.batch_size, shuffle=False, num_workers=4, drop_last=False,
                              pin_memory=True)
    return data_loader

def train_lightings_loader(args, train_type="rgb"):
    dataset = TrainLightings(args.image_size, args.data_path, train_type)
    data_loader = DataLoader(dataset=dataset, batch_size=args.batch_size, num_workers=8, shuffle=True, drop_last=False,
                              pin_memory=True)
    return data_loader

def val_lightings_loader(args, val_type="rgb"):
    dataset = ValLightings(args.image_size, args.data_path, val_type)
    data_loader = DataLoader(dataset=dataset, batch_size=args.batch_size, num_workers=8, shuffle=False, drop_last=False,
                              pin_memory=True)
    return data_loader
