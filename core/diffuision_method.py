import torch
import numpy as np
import torch.nn.functional as F
import math

from core.reconstruct_method import Reconstruct_Method
from utils.utils import t2np, KNNGaussianBlur
# from patchify import patchify
from utils.visualize_util import display_one_img, display_image
from diffusers import DDPMScheduler, UNet2DConditionModel, UniPCMultistepScheduler, DDIMScheduler
from transformers import CLIPTextModel, AutoTokenizer
from torchvision.transforms import transforms
from kornia.filters import gaussian_blur2d

from core.models.network_util import Decom_Block
from core.models.controllora import  ControlLoRAModel
from core.models.backnone import RGB_Extractor
from typing import Optional, Union, Tuple, List, Callable, Dict
from tqdm import tqdm
from torch.optim.adam import Adam
import torch.nn.functional as nnf

NUM_DDIM_STEPS = 50

class Diffusion_Method(Reconstruct_Method):
    def __init__(self, args, cls_path):
        super().__init__(args, cls_path)
        self.tokenizer = AutoTokenizer.from_pretrained(args.diffusion_id, subfolder="tokenizer")
        self.text_encoder = CLIPTextModel.from_pretrained(args.diffusion_id, subfolder="text_encoder")
        self.noise_scheduler = DDIMScheduler.from_pretrained(args.diffusion_id, subfolder="scheduler")
        self.num_inference_timesteps = int(len(self.noise_scheduler.timesteps) / args.step_size)
        self.noise_scheduler.set_timesteps(self.num_inference_timesteps)
        self.timesteps_list = self.noise_scheduler.timesteps[self.noise_scheduler.timesteps <= args.noise_intensity]
        
        self.unet = UNet2DConditionModel.from_pretrained(
        args.diffusion_id,
        subfolder="unet",
        revision=args.revision)
        
        if args.load_unet_ckpt is not None:
            self.unet.load_state_dict(torch.load(args.load_unet_ckpt, map_location=self.device))
            print("Load Diffusion Model Checkpoint!!")

        self.unet.to(self.device)
        self.text_encoder.to(self.device)
        
        self.unet.requires_grad_(False)
        self.text_encoder.requires_grad_(False)

        self.unet.eval()
        self.text_encoder.eval()
          
        
        print("Noise Intensity = ", self.timesteps_list)
        # Prepare text embedding
        self.encoder_hidden_states = self.get_text_embedding("", 6) # [6, 77, 768]
    
    def forward_process_with_T(self, latents, T):
        noise = torch.randn_like(latents)
        bsz = latents.shape[0]
        
        timesteps = torch.tensor([T], device=self.device).repeat(bsz)
        timesteps = timesteps.long()
        noisy_latents = self.noise_scheduler.add_noise(latents, noise, timesteps)
        return noise, timesteps, noisy_latents

    def get_text_embedding(self, text_prompt, bsz):
        tok = self.tokenizer(text_prompt, padding="max_length", max_length=self.tokenizer.model_max_length, truncation=True, return_tensors="pt")
        text_embedding = self.text_encoder(tok.input_ids.to(self.device).repeat(bsz,1))[0]
        return text_embedding
    
    def pixel_distance(self, output, target):
        '''
        Pixel distance between image1 and image2
        '''
        output = self.image_transform(output)
        target = self.image_transform(target)
        distance_map = torch.mean(torch.abs(output - target), dim=1).unsqueeze(1)
        return distance_map
    
    def feature_distance(self, output, target):
        '''
        Feature distance between output and target
        '''
        target = self.image_transform(target)
        output = self.image_transform(output)
        inputs_features = self.feature_extractor(target)
        output_features = self.feature_extractor(output)
        print(inputs_features.shape)
    
        out_size = self.image_size
        anomaly_map = torch.zeros([inputs_features[0].shape[0] ,1 ,out_size, out_size]).to(self.device)
        for i in range(len(inputs_features)):
            if i == 0:
                continue
            # a_map = 1 - F.cosine_similarity(patchify(inputs_features[i]), patchify(output_features[i]))
            a_map = F.mse_loss(patchify(inputs_features[i]), patchify(output_features[i]))
            print(a_map)
            a_map = torch.unsqueeze(a_map, dim=1)
            a_map = F.interpolate(a_map, size=out_size, mode='bilinear', align_corners=True)
            anomaly_map += a_map
        return anomaly_map 
    
    def heat_map(self, output, target):
        '''
        Compute the anomaly map
        :param output: the output of the reconstruction
        :param target: the target image
        :param FE: the feature extractor
        :param sigma: the sigma of the gaussian kernel
        :param i_d: the pixel distance
        :param f_d: the feature distance
        '''
        sigma = 4
        kernel_size = 2 * int(4 * sigma + 0.5) +1
        anomaly_map = 0

        output = output.to(self.device)
        target = target.to(self.device)

        i_d = self.pixel_distance(output, target)
        f_d = self.feature_distance((output),  (target))
        f_d = torch.Tensor(f_d).to(self.device)
        # print('image_distance max : ',torch.max(i_d))
        # print('feature_distance max : ',torch.max(f_d))
        # visualalize_distance(output, target, i_d, f_d)
        anomaly_map += f_d + 6.0 *  torch.max(f_d)/ torch.max(i_d) * i_d  
        anomaly_map = gaussian_blur2d(
            anomaly_map , kernel_size=(kernel_size,kernel_size), sigma=(sigma,sigma)
            )
        anomaly_map = torch.sum(anomaly_map, dim=1).unsqueeze(1)
        return anomaly_map
        
class Diffusion_Rec(Diffusion_Method):
    def __init__(self, args, cls_path):
        super().__init__(args, cls_path)
    
    def reconstruct_latents(self, latents, encoder_hidden_states):
        '''
        The reconstruction process
        :param y: the target image
        :param x: the input image
        :param seq: the sequence of denoising steps
        :param model: the UNet model
        :param x0_t: the prediction of x0 at time step t
        '''

        # Convert images to latent space
        #latents = self.get_vae_latents(lightings)
        bsz = latents.shape[0]

        # Add noise to the latents according to the noise magnitude at each timestep
        _, timesteps, noisy_latents = self.forward_process_with_T(latents, self.timesteps_list[0].item()) 

        
        # Denoising Loop
        self.noise_scheduler.set_timesteps(self.num_inference_timesteps, device=self.device)
        
        for t in self.timesteps_list:
            
            timesteps = torch.tensor([t.item()], device=self.device).repeat(bsz)
            timesteps = timesteps.long()
            noise_pred = self.unet(
                noisy_latents,
                timesteps,
                encoder_hidden_states=encoder_hidden_states,
            ).sample
        
            noisy_latents = self.noise_scheduler.step(noise_pred.to(self.device), t.item(), noisy_latents.to(self.device)).prev_sample
        
        return noisy_latents
    
    def predict(self, item, lightings, nmaps, gt, label):
        lightings = lightings.to(self.device).view(-1, 3, self.image_size, self.image_size) # [6, 3, 256, 256]
        #fc_lightings = self.get_FC_lightings(lightings)
        # nmaps = nmaps.to(self.device).repeat_interleave(6, dim=0) # [6, 3, 256, 256]
        
        latents = self.image2latents(lightings)
        rec_latents = self.reconstruct_latents(latents, self.encoder_hidden_states)
        rec_lightings = self.latents2image(rec_latents)
        latents = latents.permute(0, 2, 3, 1)
        rec_latents = rec_latents.permute(0, 2, 3, 1)
        final_map = self.pdist(latents, rec_latents)

        if self.score_type == 0:
            final_map = torch.mean(final_map, dim=0)
            final_score = torch.max(final_map)
        else:
            final_map, idx = torch.max(final_map, dim=0)
            # print(s_map_size28.shape)
            final_score = final_map[idx]

        H, W = final_map.size()
        final_map = final_map.view(1, 1, H, W)
        final_map = torch.nn.functional.interpolate(final_map, size=(self.image_size, self.image_size), mode='bilinear', align_corners=False)
        final_map = self.blur(final_map)
        img = rec_lightings[5]
        # self.cls_rec_loss += loss.item()
        self.image_labels.append(label)
        self.image_preds.append(t2np(final_score))
        self.image_list.append(t2np(img))
        self.pixel_preds.append(t2np(final_map))
        self.pixel_labels.extend(t2np(gt))
        if item % 2 == 0:
            display_image(lightings, rec_lightings, self.reconstruct_path, item)
        
class ControlNet_Rec(Diffusion_Method):
    def __init__(self, args, cls_path):
        super().__init__(args, cls_path)
        # Create ControlNet Model 
        self.controllora: ControlLoRAModel
        self.controllora = ControlLoRAModel.from_unet(self.unet, lora_linear_rank=args.controllora_linear_rank, lora_conv2d_rank=args.controllora_conv2d_rank)
        self.controllora.to(self.device)
        if args.load_controlnet_ckpt != None:
            self.controllora.load_state_dict(torch.load(args.load_controlnet_ckpt, map_location=self.device))
        self.controllora.tie_weights(self.unet)
        self.controllora.requires_grad_(False)
        self.controllora.eval()
        
    def reconstruction(self, lightings, nmaps, encoder_hidden_states):
        '''
        The reconstruction process
        :param y: the target image
        :param x: the input image
        :param seq: the sequence of denoising steps
        :param model: the UNet model
        :param x0_t: the prediction of x0 at time step t
        '''
        with torch.no_grad():
            # Convert images to latent space
            #latents = self.get_vae_latents(lightings)
            latents = self.image2latents(lightings)
            fc_latents = self.decomp_block.get_fc(latents)
            fu_latents = self.decomp_block.get_fu(latents)
            bsz = fc_latents.shape[0]

            # Add noise to the latents according to the noise magnitude at each timestep
            _, timesteps, noisy_latents = self.forward_process_with_T(fc_latents, self.timesteps_list[0].item()) 

            
            #encoder_hidden_states = lighting_text_embedding # [bs, 77, 768]
            condition_image = nmaps
            # Denoising Loop
            self.noise_scheduler.set_timesteps(self.num_inference_timesteps, device=self.device)
            
            for t in self.timesteps_list:
                
                timesteps = torch.tensor([t.item()], device=self.device).repeat(bsz)
                timesteps = timesteps.long()
                down_block_res_samples, mid_block_res_sample = self.controllora(
                    noisy_latents,
                    timesteps,
                    encoder_hidden_states=encoder_hidden_states,
                    controlnet_cond=condition_image,
                    guess_mode=False,
                    return_dict=False,
                )

                noise_pred = self.unet(
                    noisy_latents,
                    timesteps,
                    encoder_hidden_states=encoder_hidden_states,
                    down_block_additional_residuals=[sample for sample in down_block_res_samples],
                    mid_block_additional_residual=mid_block_res_sample
                ).sample
            
                noisy_latents = self.noise_scheduler.step(noise_pred.to(self.device), t.item(), noisy_latents.to(self.device)).prev_sample
            
            rec_latents = self.decomp_block.fuse_both(noisy_latents, fu_latents)
            rec_lightings = self.latents2image(rec_latents)
        return rec_lightings
        
    def predict(self, item, lightings, nmaps, gt, label):
        lightings = lightings.to(self.device).view(-1, 3, self.image_size, self.image_size) # [6, 3, 256, 256]
        #fc_lightings = self.get_FC_lightings(lightings)
        nmaps = nmaps.to(self.device).repeat_interleave(6, dim=0) # [6, 3, 256, 256]
        rec_lightings = self.reconstruction(lightings, nmaps, self.encoder_hidden_states)
        # final_map = self.heat_map(rec_lightings, lightings)
        # final_map, final_score, img = self.compute_max_smap(final_map, rec_lightings)
        # final_score = torch.max(final_map)
        
        final_map, final_score = self.compute_feature_dist(lightings, rec_lightings)
        img = rec_lightings[5]
        # self.cls_rec_loss += loss.item()
        self.image_labels.append(label)
        self.image_preds.append(t2np(final_score))
        self.image_list.append(t2np(img))
        self.pixel_preds.append(t2np(final_map))
        self.pixel_labels.extend(t2np(gt))
        if item % 2 == 0:
            display_image(t2np(lightings), t2np(rec_lightings), self.reconstruct_path, item)


class DDIM_Rec(Diffusion_Method):
    def __init__(self, args, cls_path):
        super().__init__(args, cls_path)
        
    def prev_step(self, model_output: Union[torch.FloatTensor, np.ndarray], timestep: int, sample: Union[torch.FloatTensor, np.ndarray]):
        prev_timestep = timestep - self.noise_scheduler.config.num_train_timesteps // self.noise_scheduler.num_inference_steps
        alpha_prod_t = self.noise_scheduler.alphas_cumprod[timestep]
        alpha_prod_t_prev = self.noise_scheduler.alphas_cumprod[prev_timestep] if prev_timestep >= 0 else self.scheduler.final_alpha_cumprod
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

    def ddim_loop(self, latent):
        all_latent = [latent]
        latent = latent.clone().detach()
        for t in reversed(self.timesteps_list):
            t = torch.tensor(t.item(), device=self.device)
            noise_pred = self.unet(latent, t, encoder_hidden_states=self.encoder_hidden_states)["sample"]
            latent = self.next_step(noise_pred, t, latent)
            all_latent.append(latent)
        return all_latent

    def reconstruction(
        self,
        noisy_latents,
    ):
        # latent, latents = init_latent(latent, model, height, width, generator, batch_size)
        self.noise_scheduler.set_timesteps(self.num_inference_timesteps, device=self.device)
            
        for t in self.timesteps_list:
            timesteps = torch.tensor(t.item(), device=self.device)
            # timesteps = timesteps.long()
            noise_pred = self.unet(
                noisy_latents,
                timesteps,
                encoder_hidden_states=self.encoder_hidden_states,
            ).sample
            noisy_latents = self.noise_scheduler.step(noise_pred, t.item(), noisy_latents)["prev_sample"]
        return noisy_latents
    
    def get_noise_pred(self, latents, t, is_forward=True):
        latents_input = torch.cat([latents] * 2)
        noise_pred = self.unet(latents_input, t, encoder_hidden_states=self.encoder_hidden_states)["sample"]
        # noise_pred = noise_pred_uncond
        if is_forward:
            latents = self.next_step(noise_pred, t, latents)
        else:
            latents = self.prev_step(noise_pred, t, latents)
        return latents
    
    def null_optimization(self, latents, num_inner_steps, epsilon):
        # uncond_embeddings, cond_embeddings = self.context.chunk(2)
        uncond_embeddings_list = []
        latent_cur = latents[-1]
        bar = tqdm(total=num_inner_steps * NUM_DDIM_STEPS)
        for i in range(NUM_DDIM_STEPS):
            uncond_embeddings = self.encoder_hidden_states.clone().detach()
            uncond_embeddings.requires_grad = True
            optimizer = Adam([uncond_embeddings], lr=1e-2 * (1. - i / 100.))
            latent_prev = latents[len(latents) - i - 2]
            t = self.noise_scheduler.scheduler.timesteps[i]
                # noise_pred_cond = self.unet(latents, t, encoder_hidden_states=cond_embeddings)["sample"]
                # noise_pred_cond = self.get_noise_pred_single(latent_cur, t, cond_embeddings)
            for j in range(num_inner_steps):
                noise_pred_uncond = self.unet(latents, t, encoder_hidden_states=self.encoder_hidden_states)["sample"]
                # noise_pred_uncond = self.get_noise_pred_single(latent_cur, t, uncond_embeddings)
                noise_pred = noise_pred_uncond
                latents_prev_rec = self.prev_step(noise_pred, t, latent_cur)
                loss = nnf.mse_loss(latents_prev_rec, latent_prev)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                loss_item = loss.item()
                bar.update()
                if loss_item < epsilon + i * 2e-5:
                    break
            for j in range(j + 1, num_inner_steps):
                bar.update()
            uncond_embeddings_list.append(uncond_embeddings[:1].detach())
            with torch.no_grad():
                latent_cur = self.get_noise_pred(latent_cur, t, False)
        bar.close()
        return uncond_embeddings_list
    
    def predict(self, item, lightings, nmaps, gt, label):
        lightings = lightings.to(self.device).view(-1, 3, self.image_size, self.image_size) # [6, 3, 256, 256]
        #fc_lightings = self.get_FC_lightings(lightings)
        # nmaps = nmaps.to(self.device).repeat_interleave(6, dim=0) # [6, 3, 256, 256]
        
        latents = self.image2latents(lightings)
        ddim_latents = self.ddim_loop(latents)
        rec_latents = self.reconstruction(ddim_latents[-1])
        rec_images = self.latents2image(rec_latents)
        
        latents = latents.permute(0, 2, 3, 1)
        rec_latents = rec_latents.permute(0, 2, 3, 1)
        final_map = self.pdist(latents, rec_latents)

        if self.score_type == 0:
            final_map = torch.mean(final_map, dim=0)
            final_score = torch.max(final_map)
        else:
            final_map, idx = torch.max(final_map, dim=0)
            # print(s_map_size28.shape)
            final_score = final_map[idx]

        H, W = final_map.size()
        final_map = final_map.view(1, 1, H, W)
        final_map = torch.nn.functional.interpolate(final_map, size=(self.image_size, self.image_size), mode='bilinear', align_corners=False)
        img = lightings[5]
        # self.cls_rec_loss += loss.item()
        self.image_labels.append(label)
        self.image_preds.append(t2np(final_score))
        self.image_list.append(t2np(img))
        self.pixel_preds.append(t2np(final_map))
        self.pixel_labels.extend(t2np(gt))

        display_image(lightings, rec_images, self.reconstruct_path, item)