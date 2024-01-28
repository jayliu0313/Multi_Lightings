import torch
import argparse
import numpy as np
import os
from torchvision import transforms
from tqdm import tqdm
from utils.au_pro_util import calculate_au_pro
from utils.visualize_util import *
from utils.utils import KNNGaussianBlur
from sklearn.metrics import roc_auc_score

# Diffusion model
from diffusers import DDIMScheduler
from core.models.unet_model import MyUNet2DConditionModel
from transformers import CLIPTextModel, AutoTokenizer
from diffusers import AutoencoderKL
from utils.ptp_utils import *

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]
class Base_Method():
    def __init__(self, args, cls_path):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.initialize_score()
        
        # Load vae model
        
        self.blur = KNNGaussianBlur()

        self.criteria = torch.nn.MSELoss()    
        
        self.patch_lib = []
        self.image_size = args.image_size
        
        self.cls_path = cls_path
        self.cls_rec_loss = 0.0
        self.reconstruct_path = os.path.join(cls_path, "Reconstruction")
        self.score_type = args.score_type
        
        self.pdist = torch.nn.PairwiseDistance(p=2, eps= 1e-12)
        self.average = torch.nn.AvgPool2d(3, stride=1)
        self.resize = torch.nn.AdaptiveAvgPool2d((28, 28))
        # self.blur = torch.Gua(4).to(self.device)

        self.image_transform = transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD)
        if not os.path.exists(self.reconstruct_path):
            os.makedirs(self.reconstruct_path)
            
    def initialize_score(self):
        self.image_list = list()
        self.image_preds = list()
        self.image_labels = list()
        self.pixel_preds = list()
        self.pixel_labels = list()
        self.predictions = []
        self.gts = []

    def add_sample_to_mem_bank(self, lightings):
        raise NotImplementedError
    
    def predict(self, item, lightings, gt, label):
        raise NotImplementedError
    
    def calculate_metrics(self):

        self.image_preds = np.stack(self.image_preds)
        self.image_labels = np.stack(self.image_labels)
        self.pixel_preds = np.stack(self.pixel_preds)
        self.pixel_labels = np.stack(self.pixel_labels)

        flatten_pixel_preds = self.pixel_preds.flatten()
        flatten_pixel_labels = self.pixel_labels.flatten()

        gts = np.array(self.pixel_labels).reshape(-1, self.image_size, self.image_size)
        predictions =  self.pixel_preds.reshape(-1, self.image_size, self.image_size)

        self.image_rocauc = roc_auc_score(self.image_labels, self.image_preds)
        self.pixel_rocauc = roc_auc_score(flatten_pixel_labels, flatten_pixel_preds)
        self.au_pro, _ = calculate_au_pro(gts, predictions)

        return self.image_rocauc, self.pixel_rocauc, self.au_pro
    
    def get_rec_loss(self):
        return self.cls_rec_loss
    
    def visualizae_heatmap(self):
        score_map = self.pixel_preds.reshape(-1, self.image_size, self.image_size)
        gt_mask = np.squeeze(np.array(self.pixel_labels, dtype=np.bool), axis=1)
        
        visualization(self.image_list, self.image_labels, self.image_preds, gt_mask, score_map, self.cls_path)

class DDIM_Method(Base_Method):
    def __init__(self, args, cls_path):
        super().__init__(args, cls_path)
        self.tokenizer = AutoTokenizer.from_pretrained(args.diffusion_id, subfolder="tokenizer")
        self.text_encoder = CLIPTextModel.from_pretrained(args.diffusion_id, subfolder="text_encoder")
        self.noise_scheduler = DDIMScheduler.from_pretrained(args.diffusion_id, subfolder="scheduler")
        self.num_inference_timesteps = int(len(self.noise_scheduler.timesteps) / args.step_size)
        self.noise_scheduler.set_timesteps(self.num_inference_timesteps)
        self.timesteps_list = self.noise_scheduler.timesteps[self.noise_scheduler.timesteps <= args.noise_intensity]
        self.text_encoder.to(self.device)
        self.step_size = args.step_size
        print("num_inference_timesteps")
        print("ddim loop steps:", len(self.timesteps_list))
        print("Noise Intensity = ", self.timesteps_list)
        self.unet = MyUNet2DConditionModel.from_pretrained(
            args.diffusion_id,
            subfolder="unet",
            revision=args.revision
        ).to(self.device)
        
        self.vae = AutoencoderKL.from_pretrained(
            args.diffusion_id,
            subfolder="vae",
            revision=args.revision,
            torch_dtype=torch.float32
        ).to(self.device)
        
        if args.load_unet_ckpt is not None:
            self.unet.load_state_dict(torch.load(args.load_unet_ckpt, map_location=self.device))
            print("Load Diffusion Model Checkpoint!!")
        
        if args.load_vae_ckpt is not None:
            checkpoint_dict = torch.load(args.load_vae_ckpt, map_location=self.device)
            ## Load VAE checkpoint  
            if checkpoint_dict['vae'] is not None:
                print("Load vae checkpoints!!")
                self.vae.load_state_dict(checkpoint_dict['vae'])
        
        self.vae.requires_grad_(False)
        self.unet.requires_grad_(False)
        self.text_encoder.requires_grad_(False)

        self.unet.eval()
        self.text_encoder.eval()
          
        # Prepare text embedding
        self.uncond_embeddings = self.get_text_embedding("", 6) # [6, 77, 768]
    
    @torch.no_grad()
    def image2latents(self, x):
        x = x * 2.0 - 1.0
        latents = self.vae.encode(x).latent_dist.sample()
        latents = latents * 0.18215
        return latents
    
    @torch.no_grad()
    def latents2image(self, latents):
        latents = 1 / 0.18215 * latents
        image = self.vae.decode(latents).sample
        image = (image / 2 + 0.5).clamp(0, 1)
        return image   
    
    @torch.no_grad()     
    def forward_process_with_T(self, latents, T):
        noise = torch.randn_like(latents)
        bsz = latents.shape[0]
        
        timesteps = torch.tensor([T], device=self.device).repeat(bsz)
        timesteps = timesteps.long()
        noisy_latents = self.noise_scheduler.add_noise(latents, noise, timesteps)
        return noise, timesteps, noisy_latents

    @torch.no_grad()
    def get_text_embedding(self, text_prompt, bsz):
        tok = self.tokenizer(text_prompt, padding="max_length", max_length=self.tokenizer.model_max_length, truncation=True, return_tensors="pt")
        text_embedding = self.text_encoder(tok.input_ids.to(self.device))[0].repeat((bsz, 1, 1))
        return text_embedding
    
    def prev_step(self, model_output: Union[torch.FloatTensor, np.ndarray], timestep: int, sample: Union[torch.FloatTensor, np.ndarray]):
        prev_timestep = timestep - self.noise_scheduler.config.num_train_timesteps // self.noise_scheduler.num_inference_steps
        alpha_prod_t = self.noise_scheduler.alphas_cumprod[timestep]
        alpha_prod_t_prev = self.noise_scheduler.alphas_cumprod[prev_timestep] if prev_timestep >= 0 else self.noise_scheduler.final_alpha_cumprod
        beta_prod_t = 1 - alpha_prod_t
        pred_original_sample = (sample - beta_prod_t ** 0.5 * model_output) / alpha_prod_t ** 0.5
        pred_sample_direction = (1 - alpha_prod_t_prev) ** 0.5 * model_output
        prev_sample = alpha_prod_t_prev ** 0.5 * pred_original_sample + pred_sample_direction
        return prev_sample

    def next_step(self, model_output: Union[torch.FloatTensor, np.ndarray], timestep: int, sample: Union[torch.FloatTensor, np.ndarray]):
        timestep, next_timestep = min(timestep - self.noise_scheduler.config.num_train_timesteps // self.noise_scheduler.num_inference_steps, 999), timestep
        alpha_prod_t = self.noise_scheduler.alphas_cumprod[timestep] if timestep >= 0 else self.noise_scheduler.final_alpha_cumprod
        alpha_prod_t_next = self.noise_scheduler.alphas_cumprod[next_timestep]
        beta_prod_t = 1 - alpha_prod_t
        next_original_sample = (sample - beta_prod_t ** 0.5 * model_output) / alpha_prod_t ** 0.5
        next_sample_direction = (1 - alpha_prod_t_next) ** 0.5 * model_output
        next_sample = alpha_prod_t_next ** 0.5 * next_original_sample + next_sample_direction
        return next_sample
    
    def get_noise_pred_single(self, latents, t, context):
        noise_pred = self.unet(latents, t, encoder_hidden_states=context)['sample']
        return noise_pred

    def get_noise_pred(self, latents, t, is_forward=True, context=None):
        latents_input = torch.cat([latents] * 2)
        if context is None:
            context = self.context
        guidance_scale = 1 if is_forward else self.guidance_scale
        noise_pred = self.unet(latents_input, t, encoder_hidden_states=context)["sample"]
        noise_pred_uncond, noise_prediction_text = noise_pred.chunk(2)
        noise_pred = noise_pred_uncond + guidance_scale * (noise_prediction_text - noise_pred_uncond)
        if is_forward:
            latents = self.next_step(noise_pred, t, latents)
        else:
            latents = self.prev_step(noise_pred, t, latents)
        return latents
