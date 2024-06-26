import os
import os.path as osp
import numpy as np
from sklearn.metrics import roc_auc_score, precision_recall_curve
from skimage import morphology
from skimage.segmentation import mark_boundaries
from tqdm import tqdm
from utils.utils import t2np

import matplotlib.pyplot as plt
import matplotlib
from matplotlib.lines import Line2D
matplotlib.use('Agg')
OUT_DIR = 'HeatMap'
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]
MODEL = 'PointNet'

norm = matplotlib.colors.Normalize(vmin=0.0, vmax=255.0)
cm = 4/2.54 # New
dpi = 300   # New
def min_max_normalization(data, min_val=0, max_val=1):
    min_data = np.min(data)
    max_data = np.max(data)
    normalized_data = min_val + (max_val - min_val) * (data - min_data) / (max_data - min_data)
    return normalized_data

def z_score_normalization(data):
    mean = np.mean(data)
    std = np.std(data)
    normalized_data = (data - mean) / std
    return normalized_data

def denormalization(x):
    x = (x.transpose(1, 2, 0) * 255.).astype(np.uint8)
    return x

def export_test_images(test_img, gts, scores, threshold, output_dir):
    
    image_dirs = os.path.join(output_dir, OUT_DIR ,'images')
    
    if not os.path.isdir(image_dirs):
        print('Exporting images...')
        os.makedirs(image_dirs, exist_ok=True)

        kernel = morphology.disk(2)
        scores_norm = 1.0/scores.max()
        # print(test_img.shape)
        for i in tqdm(range(0, len(test_img), 1), desc="export heat map image"):
            img = test_img[i]
            img = denormalization(img)
            
            # gts
            gt_mask = gts[i].astype(np.float64)
            gt_mask = morphology.opening(gt_mask, kernel)
            gt_mask = (255.0*gt_mask).astype(np.uint8)
            gt_img = mark_boundaries(img, gt_mask, color=(1, 0, 0), mode='thick')

            # scores
            score_mask = np.zeros_like(scores[i])
            score_mask[scores[i] >  threshold] = 1.0
            score_mask = morphology.opening(score_mask, kernel)
            score_mask = (255.0*score_mask).astype(np.uint8)
            score_img = mark_boundaries(img, score_mask, color=(1, 0, 0), mode='thick')
            score_map = (255.0*scores[i]*scores_norm).astype(np.uint8)
            #
            fig_img, ax_img = plt.subplots(3, 1, figsize=(2*cm, 6*cm))
            for ax_i in ax_img:
                ax_i.axes.xaxis.set_visible(False)
                ax_i.axes.yaxis.set_visible(False)
                ax_i.spines['top'].set_visible(False)
                ax_i.spines['right'].set_visible(False)
                ax_i.spines['bottom'].set_visible(False)
                ax_i.spines['left'].set_visible(False)
            #
            plt.subplots_adjust(hspace = 0.1, wspace = 0.1)
            ax_img[0].imshow(gt_img)
            ax_img[1].imshow(img, cmap='gray', interpolation='none')
            ax_img[1].imshow(score_map, cmap='jet', norm=norm, alpha=0.5, interpolation='none')
            ax_img[2].imshow(img)
            image_file = os.path.join(image_dirs, '{:08d}'.format(i) + '.png')
            fig_img.savefig(image_file, dpi=dpi, format='png', bbox_inches = 'tight', pad_inches = 0.0)
            plt.close()

def visualization(test_image_list, gt_label, score_label, gt_mask_list, super_mask_list, output_dir):
    
    gt_mask = np.asarray(gt_mask_list)
    super_mask = np.asarray(super_mask_list)
    
    precision, recall, thresholds = precision_recall_curve(gt_label, score_label)
    a = 2 * precision * recall
    b = precision + recall
    f1 = np.divide(a, b, out=np.zeros_like(a), where=b != 0)
    det_threshold = thresholds[np.argmax(f1)]
    # log_file.write('Optimal DET Threshold: {:.2f}\n'.format(det_threshold))

    precision, recall, thresholds = precision_recall_curve(gt_mask.flatten(), super_mask.flatten())
    a = 2 * precision * recall
    b = precision + recall
    f1 = np.divide(a, b, out=np.zeros_like(a), where=b != 0)
    seg_threshold = thresholds[np.argmax(f1)]
    # log_file.write('Optimal SEG Threshold: {:.2f}\n'.format(seg_threshold))

    export_test_images(test_image_list, gt_mask, super_mask, seg_threshold, output_dir)

def visualize_image_s_distribute(rgb_s, image_gt, output_dir):
    path_dirs = os.path.join(output_dir, OUT_DIR)
    os.makedirs(path_dirs, exist_ok=True) 
    image_file = os.path.join(path_dirs, 'image_score_dis.png')
    
    image_gt = image_gt.reshape(-1)
    colors = np.array(["blue", "red"])
    # com_s = rgb_s
    x = range(len(rgb_s))

    plt.figure(figsize=(12, 10)) 
    # plt.subplots_adjust(
    #                 bottom=0.1, 
    #                 top=0.9, 
    #                 wspace=0.2, 
    #                 hspace=0.35)
    
    # fig.text(0.5, 0.04, s = 'Image ID', ha='center', fontsize=20)
    # fig.text(0.04, 0.4, s = 'Image-level Score', ha='center', rotation='vertical', fontsize=20)
    
    # ax = fig.add_subplot(312)
    plt.title("RGB image score Distribution")
    plt.scatter(x, rgb_s, c=colors[image_gt], s=20)
    plt.plot(x, rgb_s)

    # plt.legend(loc='best')
    plt.savefig(image_file)
    plt.close()

# def visualize_image_s_distribute(sdf_s, rgb_s, image_gt, output_dir):
#     path_dirs = os.path.join(output_dir, OUT_DIR)
#     os.makedirs(path_dirs, exist_ok=True) 
#     image_file = os.path.join(path_dirs, 'image_score_dis.png')
    
#     image_gt = image_gt.reshape(-1)
#     colors = np.array(["blue", "red"])
#     com_s = sdf_s * rgb_s
#     x = range(len(sdf_s))

#     fig = plt.figure(figsize=(12, 10)) 
#     plt.subplots_adjust(
#                     bottom=0.1, 
#                     top=0.9, 
#                     wspace=0.2, 
#                     hspace=0.35)
    
#     fig.text(0.5, 0.04, s = 'Image ID', ha='center', fontsize=20)
#     fig.text(0.04, 0.4, s = 'Image-level Score', ha='center', rotation='vertical', fontsize=20)

#     ax = fig.add_subplot(311)
#     ax.set_title("SDF image score Distribution", fontsize=18)
#     ax.scatter(x, sdf_s, c=colors[image_gt], s=50)
#     ax.plot(x, sdf_s)
    
#     ax = fig.add_subplot(312)
#     ax.set_title("RGB image score Distribution", fontsize=18)
#     ax.scatter(x, rgb_s, c=colors[image_gt], s=50)
#     ax.plot(x, rgb_s)

#     ax = fig.add_subplot(313)
#     ax.set_title("Shape-Guided image score Distribution", fontsize=18)
#     ax.scatter(x, com_s, c=colors[image_gt], s=50)
#     ax.plot(x, com_s)
#     # plt.legend(loc='best')
#     plt.savefig(image_file)
#     plt.close()

def visualize_perpixel_distribute(score_map, gt_map, output_dir, name):
    path_dirs = output_dir
    os.makedirs(path_dirs, exist_ok=True)
    
    image_file = os.path.join(path_dirs, name)
    gt_map = np.array(gt_map)
    gt_map = gt_map.flatten()
    
    anomalous_label = np.where(gt_map == 1)[0]
    normal_label = np.where(gt_map == 0)[0]

    anomalous_distribution = score_map[anomalous_label]
    normal_distribution = score_map[normal_label]
    # normal_distribution = normal_distribution[normal_distribution != 1]
    normal_mean = np.mean(normal_distribution)
    anomalous_mean = np.mean(anomalous_distribution)
    distance = np.abs(anomalous_mean - normal_mean)
    print(output_dir)
    print(f"Method {name} Distance:{distance}")
    print("------------------------------------------------------------------------------------------")
    fig, ax1 = plt.subplots(figsize=(16, 8))
    fig.subplots_adjust(top=0.9)
    fig.text(0.5, 0.02, s='Per-Pixel Feature Distance', ha='center', fontsize=35)

    ax1.tick_params(axis='x', labelsize=25)
    ax1.tick_params(axis='y', labelsize=20)
    # if name == "distribution_wonormalize":
    #     ax1.set_xlim(0, 75)
    # Plot normal distribution on the left axis (ax1)
    ax1.hist(normal_distribution, bins=100, color='g', alpha=0.7)
    ax1.set_ylabel('Number of Pixels (Normal)', fontsize=35)
    # ax1.set_title("Distribution", fontsize=35)
    
    # Create a twin axis sharing the xaxis with ax1
    ax2 = ax1.twinx()
    ax2.tick_params(axis='y', labelsize=20)

    # Plot anomalous distribution on the right axis (ax2)
    ax2.hist(anomalous_distribution, bins=100, color='r', alpha=0.7)
    ax2.set_ylabel('Number of Pixels (Anomalous)', fontsize=35)
    
    # 在圖上顯示三條直線，表示平均值
    ax1.axvline(normal_mean, color='darkgreen', linestyle='dashed', linewidth=4, label='Normal Mean')
    ax1.axvline(anomalous_mean, color='darkred', linestyle='dashed', linewidth=4, label='Anomaly Mean')
    # ax1.axvline(overall_mean, linestyle='dashed', linewidth=6, label='Overall Mean')
    

    legend_elements_mean = [
        Line2D([0], [0], color='darkgreen', lw=5, linestyle='dashed', label='Normal Mean'),
        Line2D([0], [0], color='darkred', lw=5, linestyle='dashed', label='Anomaly Mean'),
    ]
    # Add legend in the top right corner
    ax1.legend(handles=legend_elements_mean, loc='upper right', fontsize=23, framealpha=0.3)
    ax2.legend(handles=legend_elements_mean, loc='upper right', fontsize=23, framealpha=0.3)
    plt.savefig(image_file)
    plt.close()

# def visualize_perpixel_distribute(score_map, gt_map):
#     path_dirs = "./output_dir/" + OUT_DIR
#     os.makedirs(path_dirs, exist_ok=True)
#     image_file = os.path.join(path_dirs, 'category_all_ditribution.png')
#     gt_map = np.array(gt_map)

#     score_map = score_map.flatten()
#     gt_map = gt_map.flatten()
    
#     anomalous_label = np.where(gt_map == 1)[0]
#     normal_label = np.where(gt_map == 0)[0]

#     anomalous_distribution = score_map[anomalous_label]
#     normal_distribution = score_map[normal_label]

#     normal_distribution = normal_distribution[normal_distribution != 1]
#     # print(score_non_zero_indices.shape)
#     # print(score_non_zero_indices)
#     # print(score_map)
   
#     fig, ax = plt.subplots(figsize=(14, 16))
#     fig.text(0.5, 0.04, s = 'pixel-level score', ha='center', fontsize=25)
#     fig.text(0.04, 0.45, s = 'number of pixel', ha='center', rotation='vertical', fontsize=25)
    
#     ax.tick_params(axis='x', labelsize=15)
#     ax.tick_params(axis='y', labelsize=15)
#     ax.hist(anomalous_distribution, bins=100, alpha=0.5, color='r', label='Anomalous Distribution')
#     # ax.set_title("anomalous Distribution", fontsize=20)

#     # ax.tick_params(axis='x', labelsize=15)
#     # ax.tick_params(axis='y', labelsize=15)
#     ax.hist(normal_distribution, bins=100, alpha=0.5, color='g', label='Normal Distribution')
#     # ax.set_title("normal Distribution", fontsize=20)
#     plt.savefig(image_file)
#     plt.close()
######################################
    # ax = fig.add_subplot(413)
    # ax.hist(non_min_rgb_map, bins=100, color='b')
    # ax.title.set_text("RGB Distribution")

    # ax = fig.add_subplot(414)
    # ax.hist(non_min_new_rgb, bins=100, color='c')
    # ax.title.set_text("New RGB Distribution")



    # total_map = total_map.reshape(-1, image_size * image_size)
    # sdf_map = sdf_map.reshape(-1, image_size * image_size)
    # rgb_map = rgb_map.reshape(-1, image_size * image_size)
    # new_rgb_map = new_rgb_map.reshape(-1, image_size * image_size)
    # for i in tqdm(range(0, len(total_map), 5), desc='export score map distribution'):
    #     image_file = os.path.join(path_dirs, '{:08d}'.format(i) + '.png')
    #     non_min_total_map = total_map[i][total_map[i] > total_map[i].min()]
    #     non_min_sdf_map = sdf_map[i][sdf_map[i] > sdf_map[i].min()]
    #     non_min_rgb_map = rgb_map[i][rgb_map[i] > rgb_map[i].min()]
    #     non_min_new_rgb = new_rgb_map[i][new_rgb_map[i] > new_rgb_map[i].min()]
        
    #     fig = plt.figure(figsize=(14, 16))
    #     fig.text(0.5, 0.04, s = 'pixel-level score', ha='center', fontsize=20)
    #     fig.text(0.04, 0.45, s = 'number of pixel', ha='center', rotation='vertical', fontsize=20)

    #     ax1 = fig.add_subplot(411)
    #     ax1.hist(non_min_total_map, bins=100, color='r')
    #     ax1.title.set_text("Total Distribution")
        
    #     ax1 = fig.add_subplot(412)
    #     ax1.hist(non_min_sdf_map, bins=100, color='g')
    #     ax1.title.set_text("SDF Distribution")

    #     ax1 = fig.add_subplot(413)
    #     ax1.hist(non_min_rgb_map, bins=100, color='b')
    #     ax1.title.set_text("Original RGB Distribution")

    #     ax1 = fig.add_subplot(414)
    #     ax1.hist(non_min_new_rgb, bins=100, color='c')
    #     ax1.title.set_text("Adjust RGB Distribution")
        
    #     plt.savefig(image_file)
    #     plt.close()

def display_image(images, reconstruct_imgs, save_path, item):
    images = images.permute(0, 2, 3, 1)
    images = t2np(images)
    reconstruct_imgs = reconstruct_imgs.permute(0, 2, 3, 1)
    reconstruct_imgs = t2np(reconstruct_imgs)
    image_size = images.shape[2] 
    fig = plt.figure(figsize=(12, 5))
    nrows = 2
    ncols = 6
    for i in range(6): 
        img = images[i, :, :, :].reshape(image_size, image_size, 3)
        fig.add_subplot(nrows, ncols, i + 1)
        plt.imshow(img, cmap='gray')
        plt.axis("off")
        if(i == 2):
            plt.title('Lighting Image', fontsize = 15)

        target = reconstruct_imgs[i, :, :, :].reshape(image_size, image_size, 3)
        fig.add_subplot(nrows, ncols, 7 + i)
        plt.imshow(target, cmap='gray')
        plt.axis("off")
        if(i == 2):
            plt.title('Reconstruct Image', fontsize = 15)
    
    
    plt.savefig(save_path, dpi=300)
    plt.close()
    
def display_3type_image(images, reconstruct_imgs, augment_img, cls_path, item):
    images = images.permute(0, 2, 3, 1)
    images = t2np(images)
    
    reconstruct_imgs = reconstruct_imgs.permute(0, 2, 3, 1)
    reconstruct_imgs = t2np(reconstruct_imgs)
    
    augment_img = augment_img.permute(0, 2, 3, 1)
    augment_img = t2np(augment_img)
    
    save_path = os.path.join(cls_path, str(item) +".png")
    image_size = images.shape[2] 
    fig = plt.figure(figsize=(12, 5))
    nrows = 3
    ncols = 6
    for i in range(6): 
        img = images[i, :, :, :].reshape(image_size, image_size, 3)
        fig.add_subplot(nrows, ncols, i + 1)
        plt.imshow(img, cmap='gray')
        plt.axis("off")
        if(i == 2):
            plt.title('Lighting Image', fontsize = 15)

        target = reconstruct_imgs[i, :, :, :].reshape(image_size, image_size, 3)
        fig.add_subplot(nrows, ncols, 7 + i)
        plt.imshow(target, cmap='gray')
        plt.axis("off")
        if(i == 2):
            plt.title('Reconstruct Image', fontsize = 15)
            
        aug = augment_img[i, :, :, :].reshape(image_size, image_size, 3)
        fig.add_subplot(nrows, ncols, 13 + i)
        plt.imshow(aug, cmap='gray')
        plt.axis("off")
        if(i == 2):
            plt.title('Augment Image', fontsize = 15)
            
    plt.savefig(save_path, dpi=300)
    plt.close()

def display_mean_fusion(images, reconsturct_imgs, cls_path, item):
    save_path = os.path.join(cls_path, str(item) +".png")
    image_size = images.shape[2] 
    fig = plt.figure(figsize=(12, 5))
    nrows = 2
    ncols = 6
    for i in range(6):
        img = denormalization(images[i, :, :, :].reshape(-1, image_size, image_size))
        fig.add_subplot(nrows, ncols, i + 1)
        plt.imshow(img, cmap='gray')
        plt.axis("off")
        if(i == 2):
            plt.title('Unique Testing Image', fontsize = 15)

        target = denormalization(reconsturct_imgs[i, :, :, :].reshape(-1, image_size, image_size))
        fig.add_subplot(nrows, ncols, 7 + i)
        plt.imshow(target, cmap='gray')
        plt.axis("off")
        if(i == 2):
            plt.title('Reconstruct Testing Image', fontsize = 15)
    
    plt.savefig(save_path, dpi=300)
    plt.close()   
    
def display_one_img(img, rec, save_path):
    # save_path = os.path.join(cls_path, str(item) + "_normal.png")

    fig = plt.figure(figsize=(12, 5))
    img = denormalization(img)
    fig.add_subplot(2, 1, 1)
    plt.imshow(img, cmap='gray')
    plt.axis("off")
    plt.title('Testing Image', fontsize = 15)

    target = denormalization(rec)
    fig.add_subplot(2, 1, 2)
    plt.imshow(target, cmap='gray')
    plt.axis("off")
    plt.title('Reconstruct Testing Image', fontsize = 15)

    plt.savefig(save_path, dpi=300)
    plt.close()


"""
def export_hist(gts, scores, threshold, output_dir):
    print('Exporting histogram...')
    plt.rcParams.update({'font.size': 4})
    image_dirs = os.path.join(output_dir, OUT_DIR)
    os.makedirs(image_dirs, exist_ok=True)
    Y = scores.flatten()
    Y_label = gts.flatten()
    fig = plt.figure(figsize=(4*cm, 4*cm), dpi=dpi)
    ax = plt.Axes(fig, [0., 0., 1., 1.])
    fig.add_axes(ax)
    plt.hist([Y[Y_label==1], Y[Y_label==0]], 500, density=True, color=['r', 'g'], label=['ANO', 'TYP'], alpha=0.75, histtype='barstacked')
    image_file = os.path.join(image_dirs, 'hist_images.svg')
    fig.savefig(image_file, dpi=dpi, format='svg', bbox_inches = 'tight', pad_inches = 0.0)
    plt.close()


def export_groundtruth(test_img, gts, output_dir):
    image_dirs = os.path.join(output_dir, OUT_DIR, 'gt_images')
    # images
    if not os.path.isdir(image_dirs):
        print('Exporting grountruth...')
        os.makedirs(image_dirs, exist_ok=True)
        num = len(test_img)
        kernel = morphology.disk(4)
        for i in range(num):
            img = test_img[i]
            img = denormalization(img, IMAGENET_MEAN, IMAGENET_STD)
            # gts
            gt_mask = gts[i].astype(np.float64)
            #gt_mask = morphology.opening(gt_mask, kernel)
            gt_mask = (255.0*gt_mask).astype(np.uint8)
            gt_img = mark_boundaries(img, gt_mask, color=(1, 0, 0), mode='thick')
            #
            fig = plt.figure(figsize=(2*cm, 2*cm), dpi=dpi)
            ax = plt.Axes(fig, [0., 0., 1., 1.])
            ax.set_axis_off()
            fig.add_axes(ax)
            ax.imshow(gt_img)
            image_file = os.path.join(image_dirs, '{:08d}'.format(i) + '.svg')
            fig.savefig(image_file, dpi=dpi, format='svg', bbox_inches = 'tight', pad_inches = 0.0)
            plt.close()

def export_scores(test_img, scores, threshold, output_dir):
    image_dirs = os.path.join(output_dir, OUT_DIR, 'sc_images')
    # images
    if not os.path.isdir(image_dirs):
        print('Exporting scores...')
        os.makedirs(image_dirs, exist_ok=True)
        num = len(test_img)
        kernel = morphology.disk(4)
        scores_norm = 1.0/scores.max()
        for i in range(num):
            img = test_img[i]
            img = denormalization(img, IMAGENET_MEAN, IMAGENET_STD)

            # scores
            score_mask = np.zeros_like(scores[i])
            score_mask[scores[i] >  threshold] = 1.0
            score_mask = morphology.opening(score_mask, kernel)
            score_mask = (255.0*score_mask).astype(np.uint8)
            score_img = mark_boundaries(img, score_mask, color=(1, 0, 0), mode='thick')
            score_map = (255.0*scores[i]*scores_norm).astype(np.uint8)
            #
            fig_img, ax_img = plt.subplots(2, 1, figsize=(2*cm, 4*cm))
            for ax_i in ax_img:
                ax_i.axes.xaxis.set_visible(False)
                ax_i.axes.yaxis.set_visible(False)
                ax_i.spines['top'].set_visible(False)
                ax_i.spines['right'].set_visible(False)
                ax_i.spines['bottom'].set_visible(False)
                ax_i.spines['left'].set_visible(False)
            #
            plt.subplots_adjust(hspace = 0.1, wspace = 0.1)
            ax_img[0].imshow(img, cmap='gray', interpolation='none')
            ax_img[0].imshow(score_map, cmap='jet', norm=norm, alpha=0.5, interpolation='none')
            ax_img[1].imshow(score_img)
            image_file = os.path.join(image_dirs, '{:08d}'.format(i) + '.svg')
            fig_img.savefig(image_file, dpi=dpi, format='svg', bbox_inches = 'tight', pad_inches = 0.0)
            plt.close()

"""