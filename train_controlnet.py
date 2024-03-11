import os
import argparse
import numpy as np
from tqdm import tqdm
import os.path as osp
import itertools
import torch
import torch.nn as nn
import torch.nn.functional as F


from core.data import train_lightings_loader, val_lightings_loader, mvtec3D_train_loader, mvtec3D_val_loader
from transformers import CLIPTextModel, AutoTokenizer
from diffusers import AutoencoderKL, DDPMScheduler
from diffusers.optimization import get_scheduler
from core.models.unet_model import build_unet
from core.models.controllora import ControlLoRAModel
# from utils.performace_testing import Memorybank_testing

import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')
os.environ["TOKENIZERS_PARALLELISM"] = "false"

parser = argparse.ArgumentParser(description='train')
parser.add_argument('--data_path', default="/mnt/home_6T/public/jayliu0313/datasets/mvtec3d_preprocessing/", type=str)
parser.add_argument('--ckpt_path', default="./checkpoints/controlnet_model/MVTec3D_V1-4_Aug/") # 
parser.add_argument('--load_vae_ckpt', default=None)
parser.add_argument('--load_unet_ckpt', default="checkpoints/diffusion_checkpoints/TrainUnetMVTec3D_DepthRGB_V1-4_Aug/best_unet.pth")
parser.add_argument('--image_size', default=256, type=int)
parser.add_argument('--batch_size', default=16, type=int)
parser.add_argument('--dataset_type', default="mvtec3d", help="eyecandies, mvtec3d")

# Model Setup
parser.add_argument("--diffusion_id", type=str, default="CompVis/stable-diffusion-v1-4")
parser.add_argument("--revision", type=str, default="ebb811dd71cdc38a204ecbdd6ac5d580f529fd8c")
parser.add_argument("--controllora_linear_rank",type=int, default=4)
parser.add_argument("--controllora_conv2d_rank",type=int,default=0)

# Training Setup
parser.add_argument("--learning_rate", default=5e-6)
parser.add_argument('--weight_decay', type=float, default=0.05, help='weight decay (default: 0.05)')
parser.add_argument("--adam_beta1", type=float, default=0.9, help="The beta1 parameter for the Adam optimizer.")
parser.add_argument("--adam_beta2", type=float, default=0.999, help="The beta2 parameter for the Adam optimizer.")
parser.add_argument("--adam_weight_decay", type=float, default=1e-2, help="Weight decay to use.")
parser.add_argument("--adam_epsilon", type=float, default=1e-08, help="Epsilon value for the Adam optimizer")
parser.add_argument("--workers", default=4)
parser.add_argument('--CUDA', type=int, default=0, help="choose the device of CUDA")
parser.add_argument("--lr_scheduler", type=str, default="constant", help=('The scheduler type to use. Choose between ["linear", "cosine", "cosine_with_restarts", "polynomial",'' "constant", "constant_with_warmup"]'),)
parser.add_argument("--max_grad_norm", default=1.0, type=float, help="Max gradient norm.")
parser.add_argument('--epoch', default=0, type=int, help="Which epoch to start training at")
parser.add_argument("--num_train_epochs", type=int, default=100)
parser.add_argument("--lr_warmup_steps", type=int, default=0, help="Number of steps for the warmup in the lr scheduler.")
parser.add_argument("--save_epoch", type=int, default=3)


def export_loss(save_path, loss_list):
    epoch_list = range(len(loss_list))
    plt.rcParams.update({'font.size': 30})
    plt.title('Training Loss Curve') # set the title of graph
    plt.figure(figsize=(20, 15))
    plt.plot(epoch_list, loss_list, color='b')
    plt.xticks(np.arange(0, len(epoch_list)+1, 50))
    plt.xlabel('Epoch') # set the title of x axis
    plt.ylabel('Loss')
    plt.savefig(save_path)
    plt.clf()
    plt.cla()
    plt.close("all")

class TrainUnet():
    def __init__(self, args, device):

        self.device = device
        self.bs = args.batch_size
        self.image_size = args.image_size
        self.num_train_epochs = args.num_train_epochs
        self.save_epoch = args.save_epoch
        self.train_log_file = open(osp.join(args.ckpt_path, "training_log.txt"), "a", 1)
        self.val_log_file = open(osp.join(args.ckpt_path, "val_log.txt"), "a", 1)

        # Load training and validation data
        if args.dataset_type == "eyecandies":
            self.train_dataloader = train_lightings_loader(args)
            self.val_dataloader = val_lightings_loader(args)
        elif args.dataset_type == "mvtec3d":
            self.train_dataloader = mvtec3D_train_loader(args)
            self.val_dataloader = mvtec3D_val_loader(args)

        # Create Model
        self.tokenizer = AutoTokenizer.from_pretrained(args.diffusion_id, subfolder="tokenizer")
        self.text_encoder = CLIPTextModel.from_pretrained(args.diffusion_id, subfolder="text_encoder")
        self.noise_scheduler = DDPMScheduler.from_pretrained(args.diffusion_id, subfolder="scheduler")

        self.vae = AutoencoderKL.from_pretrained(
            args.diffusion_id,
            subfolder="vae",
            revision=args.revision,
        ).to(self.device)
        self.unet = build_unet(args)
        self.unet.load_state_dict(torch.load(args.load_unet_ckpt, map_location=self.device))
        self.controllora = ControlLoRAModel.from_unet(self.unet, lora_linear_rank=args.controllora_linear_rank, lora_conv2d_rank=args.controllora_conv2d_rank)

        self.vae.requires_grad_(False)
        self.unet.requires_grad_(False)
        self.text_encoder.requires_grad_(False)
        self.controllora.train()

        self.vae.to(self.device)
        self.unet.to(self.device)
        self.text_encoder.to(self.device)
        self.controllora.to(self.device)

        # Optimizer creation 
        self.optimizer = torch.optim.AdamW(
            self.controllora.parameters(),
            lr=args.learning_rate,
            betas=(args.adam_beta1, args.adam_beta2),
            weight_decay=args.adam_weight_decay,
            eps=args.adam_epsilon,
        )

        self.lr_scheduler = get_scheduler(
            args.lr_scheduler,
            optimizer=self.optimizer,
            num_warmup_steps=0,
            num_training_steps=len(self.train_dataloader) * args.num_train_epochs,
            num_cycles=1,
            power=1.0,
        )

    def image2latents(self, x):
        x = x * 2.0 - 1.0
        latents = self.vae.encode(x).latent_dist.sample()
        latents = latents * 0.18215
        return latents

    def latents2image(self, latents):
        latents = 1 / 0.18215 * latents
        image = self.vae.decode(latents).sample
        return image.clamp(-1, 1)

    def forward_process(self, x_0):
        noise = torch.randn_like(x_0) # Sample noise that we'll add to the latents
        bsz = x_0.shape[0]

        timestep = torch.randint(1, self.noise_scheduler.config.num_train_timesteps, (bsz,), device=self.device) # Sample a random timestep for each image
        timestep = timestep.long()
        x_t = self.noise_scheduler.add_noise(x_0, noise, timestep) # Corrupt image
        return noise, timestep, x_t

    def get_text_embedding(self, text_prompt):
        with torch.no_grad():
            tok = self.tokenizer(text_prompt, padding="max_length", max_length=self.tokenizer.model_max_length, truncation=True, return_tensors="pt")
            text_embedding = self.text_encoder(tok.input_ids.to(self.device))[0]
        return text_embedding

    def log_validation(self):

        val_loss = 0.0
        for lightings, nmaps, text_prompt in tqdm(self.val_dataloader, desc="Validation"):

            with torch.no_grad():
                lightings = lightings.to(self.device) # [bs, 6, 3, 256, 256]
                nmaps = nmaps.to(self.device)         # [bs, 6, 3, 256, 256]

                # single_lightings = lightings[:, 5, :, :, :] # [bs, 3, 256, 256]
                lightings = lightings.view(-1, 3, self.image_size, self.image_size) # [bs * 6, 3, 256, 256]
                # repeat_nmaps = nmaps.repeat_interleave(6, dim=0)                    # [bs * 6, 3, 256, 256]
                
                # Get text embedding from CLIP
                text_embs = self.get_text_embedding(text_prompt)  # [bs    , 7, 768]
                # text_embs = text_emb.repeat_interleave(6, dim=0) # [bs * 6, 7, 768]
                encoder_hidden_states = torch.cat((text_embs, text_embs), dim=0) # [bs * 7, 77, 768]
                
                # Convert images to latent space
                rgb_latents = self.image2latents(lightings)        # [bs * 6, 4, 32, 32]
                nmap_latents = self.image2latents(nmaps)           # [bs    , 4, 32, 32]
                input_latent = torch.cat((rgb_latents, nmap_latents), dim=0) # [bs * 7, 4, 32, 32]

                # Add noise to the latents according to the noise magnitude at each timestep
                noise, timesteps, noisy_latents = self.forward_process(input_latent)
                
                # Training ControlNet
                condition_image = torch.cat((nmaps, lightings), dim=0) # [bs * 7, 3, 256, 256]
                down_block_res_samples, mid_block_res_sample = self.controllora(
                    noisy_latents,
                    timesteps,
                    encoder_hidden_states=encoder_hidden_states,
                    controlnet_cond=condition_image,
                    return_dict=False,
                )

                # Predict the noise from Unet
                model_output = self.unet(
                    noisy_latents,
                    timesteps,
                    encoder_hidden_states=encoder_hidden_states,
                    down_block_additional_residuals=[sample for sample in down_block_res_samples],
                    mid_block_additional_residual=mid_block_res_sample
                )
                pred_noise = model_output['sample']
                
                # Compute loss and optimize model parameter
                loss = F.mse_loss(pred_noise.float(), noise.float(), reduction="mean")
                val_loss += loss.item()

        val_loss /= len(self.val_dataloader)
        print('Validation Loss: {:.6f}'.format(val_loss))
        self.val_log_file.write('Validation Loss: {:.6f}\n'.format(val_loss))
        return val_loss

    #####################################################################
    #                            Start Training                         #
    #####################################################################
    def train(self):
        
        loss_list = []
        val_loss_list = []
        val_best_loss = float('inf')

        for epoch in range(self.num_train_epochs):

            epoch_loss = 0.0

            for lightings, nmaps, text_prompt in tqdm(self.train_dataloader, desc="Training"):

                self.optimizer.zero_grad()
                lightings = lightings.to(self.device) # [bs, 6, 3, 256, 256]
                nmaps = nmaps.to(self.device)         # [bs, 6, 3, 256, 256]

                # single_lightings = lightings[:, 5, :, :, :] # [bs, 3, 256, 256]
                lightings = lightings.view(-1, 3, self.image_size, self.image_size) # [bs * 6, 3, 256, 256]
                # repeat_nmaps = nmaps.repeat_interleave(6, dim=0)                    # [bs * 6, 3, 256, 256]
                
                # Get text embedding from CLIP
                text_embs = self.get_text_embedding(text_prompt)  # [bs    , 7, 768]
                # text_embs = text_emb.repeat_interleave(6, dim=0) # [bs * 6, 7, 768]
                encoder_hidden_states = torch.cat((text_embs, text_embs), dim=0) # [bs * 7, 77, 768]
                
                # Convert images to latent space
                rgb_latents = self.image2latents(lightings)        # [bs * 6, 4, 32, 32]
                nmap_latents = self.image2latents(nmaps)           # [bs    , 4, 32, 32]
                input_latent = torch.cat((rgb_latents, nmap_latents), dim=0) # [bs * 7, 4, 32, 32]

                # Add noise to the latents according to the noise magnitude at each timestep
                noise, timesteps, noisy_latents = self.forward_process(input_latent)
                
                # Training ControlNet
                condition_image = torch.cat((nmaps, lightings), dim=0) # [bs * 7, 3, 256, 256]
                down_block_res_samples, mid_block_res_sample = self.controllora(
                    noisy_latents,
                    timesteps,
                    encoder_hidden_states=encoder_hidden_states,
                    controlnet_cond=condition_image,
                    return_dict=False,
                )

                # Predict the noise from Unet
                model_output = self.unet(
                    noisy_latents,
                    timesteps,
                    encoder_hidden_states=encoder_hidden_states,
                    down_block_additional_residuals=[sample for sample in down_block_res_samples],
                    mid_block_additional_residual=mid_block_res_sample
                )
                pred_noise = model_output['sample']
                
                # Compute loss and optimize model parameter
                loss = F.mse_loss(pred_noise.float(), noise.float(), reduction="mean")
                loss.backward()

                epoch_loss += loss.item()
                nn.utils.clip_grad_norm_(self.controllora.parameters(), args.max_grad_norm)
                self.optimizer.step()
                self.lr_scheduler.step()

            epoch_loss /= len(self.train_dataloader)

            loss_list.append(epoch_loss)
            print('Training-Epoch {} Loss: {:.6f}'.format(epoch, epoch_loss))
            self.train_log_file.write('Training-Epoch {} Loss: {:.6f}\n'.format(epoch, epoch_loss))

            # save model
            with torch.no_grad():
                if epoch % self.save_epoch == 0:
                    export_loss(args.ckpt_path + '/total_loss.png', loss_list)

                    val_loss = self.log_validation() # Evaluate
                    val_loss_list.append(val_loss)
                    export_loss(args.ckpt_path + '/val_loss.png', val_loss_list)
                    if val_loss < val_best_loss:
                        val_best_loss = val_loss
                        model_path = args.ckpt_path + f'/best_controlnet.pth'
                        torch.save(self.controllora.state_dict(), model_path)
                        print("### Save Model ###")
                if epoch % 50 == 0 and epoch != 0:
                    model_path = args.ckpt_path + f'/epoch{epoch}_controlnet.pth'
                    torch.save(self.controllora.state_dict(), model_path)
                    print("### Save Epoch Model ###")


if __name__ == "__main__":

    args = parser.parse_args()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Current Device = {device}")

    if not os.path.exists(args.ckpt_path):
        os.makedirs(args.ckpt_path)

    runner = TrainUnet(args=args, device=device)
    runner.train()