# Learning Diffusion Models for Multi-View Anomaly Detection

## Installation
### Requirement
Linux (Ubuntu 16.04)  
Python 3.6+  
PyTorch 1.7 or higher  
CUDA 10.2 or higher

### create environment
```
git clone https://github.com/jayliu0313/Multi_Lightings.git
cd Multi_Lightings
conda create --name myenv python=3.6
conda activate myenv
pip install -r requirement.txt
```
### Eyecandies Dataset
[Here](https://eyecan-ai.github.io/eyecandies/download) to download dataset

### MvTec3D-AD Dataset
[Here](https://www.mvtec.com/company/research/datasets/mvtec-3d-ad) to download dataset

## Implementation
### Finetune the UNet and CountrolNet
```
python train_unifiedunet.py --data_path DATASET_PATH --ckpt_path SAVE_PATH
```
```
python train_controlnet.py --data_path DATASET_PATH --load_unet_ckpt UNET_CKPT_PATH --ckpt_path SAVE_PATH
```

### Buid Memory and Inference
The result will be stored in the output directory.
You can use "--vis" to visualize our result of the heat map. 
```
python test.py --data_path DATASET_PATH --load_unet_ckpt UNET_CKPT_PATH  --load_controlnet_ckpt CONTROLNET_CKPT_PATH
```