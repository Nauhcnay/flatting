import os, sys
import numpy as np
import cv2
import torch
from multiprocessing import Process, Queue

from os.path import *
sys.path.append(join(dirname(abspath(__file__)), "trapped_ball"))
from run import region_get_map, merge_to_ref, verify_reigon
from predict import predict_img
from thinning import thinning
from unet import UNet
from PIL import Image

# global variables shared by all api functions
nets = {}
queue = Queue

def initial_models(path_to_ckpt):

    # find the lastest model
    ckpt_list = []
    
    if ".pth" not in path_to_ckpt:
        for c in os.listdir(path_to_ckpt):
            if ".pth" in c:
                ckpt_list.append(c)
        ckpt_list.sort()
        path_to_ckpt = join(path_to_ckpt, ckpt_list[-1])

    assert exists(path_to_ckpt)
    
    # init model
    net = UNet(in_channels=1, out_channels=1, bilinear=True)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    net.to(device=device)
    
    # load model
    print("Log:\tload %s"%path_to_ckpt)
    try:
        net.load_state_dict(torch.load(path_to_ckpt, map_location=device))
    except:
        net = torch.nn.DataParallel(net)
        net.load_state_dict(torch.load(path_to_ckpt, map_location=device))
    net.eval()

    return net, device

def initial_nets(force_refresh=False):
    '''
        Load trained U-Net models to nets
    '''
    global nets

    try:
        if len(nets) == 0 or force_refresh:
            path_1024 = "./checkpoints/rand_1024/"
            path_1024_base = "./checkpoints/base_1024/"
            path_512_base = "./checkpoints/base_512/"
            path_512 = "./checkpoints/rand_512/"
            nets["1024"] = initial_models(path_1024)
            nets["1024_base"] = initial_models(path_1024_base)

            nets["512"] = initial_models(path_512)
            nets["512_base"] = initial_models(path_512_base)

        return True
    except:
        return False

def add_white(img, return_numpy = False):
    img = np.array(img)
    if len(img.shape) == 3:
        if img.shape[2] == 4:
            img = 255 - img[:,:,3]
            img[img < 250] = 0
    if return_numpy:
        return img
    else:
        return Image.fromarray(img)

def add_alpha(img, line_color = None):
    if img.mode != "RGBA":
        img = img.convert("RGB")
    img = np.array(img)
    
    if img.shape[2] == 4:
        return Image.fromarray(img)
    
    h, w, _ = img.shape
    img_alpha = np.zeros((h,w,4), dtype = np.uint8)
    img_alpha[:,:,:3] = img.copy()

    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
    img_alpha[:,:,3] = 255 - img

    if isinstance(line_color, str):
        assert len(line_color) == 6
        r = int(line_color[0:2], 16)
        g = int(line_color[2:4], 16)
        b = int(line_color[4:6], 16)
        img_alpha[:,:,0] = r
        img_alpha[:,:,1] = g
        img_alpha[:,:,2] = b

    return img_alpha

def fillmap_masked_line(fill_map, line_input):
        edges = cv2.Canny(fill_map.astype(np.uint8), 0, 0)
        kernel = np.ones((5,5),np.uint8)
        edges = cv2.dilate(edges, kernel, iterations = 2)
        result = np.array(line_input).copy()
        result[edges == 0] = 255
        return Image.fromarray(result)

def run_single(line_artist, net, radius, preview=False):
    '''
    Given:
        line_artst, the line art drawn by artist, 
            it should be a binary image, contains paint storkes only
        nets, the trained U-net to simplify artist line
        radius, the trapped ball filling radius
        preview, return the coarse preview result, 
            this option will be much faster than getting the full results
    Return:
        fill_map, the final fill map, each region is given a number label
            it comes from the combination o ftrapped ball filling on 
            simplified line and connected component filling on artist line
        fill, the colored fill_map
        fill_map_artist, the connect component fill map on artist line
            it usually contain much more splited regions than fill_map
        fill_artist, the colored fill_map_artist
    '''
    assert initial_nets()
    global nets

    line_input = add_white(line_artist)

    # simplify artist line
    if str(nets[net][1]) == 'cpu':
        print("Warning:\tno gpu found, using cpu mode, the inference may be slow")
    
    print("Log:\tsimplify artist line")
    size = int(net.split("_")[0])
    line_simplify = predict_img(net=nets[net][0],
                       full_img=line_input,
                       device=nets[net][1],
                       size = int(size))

    # filling and refine
    # we should add a multiprocess here
    print("Log:\ttrapping ball filling with radius %s"%str(radius))

    if preview:
        return region_get_map(line_simplify,
                path_to_line_artist=line_input,  
                radius_set=[int(radius)], percentiles=[0],
                preview=preview
                )
    else:
        fill_map, fill_map_neural, fill_map_artist = region_get_map(line_simplify,
                                                    path_to_line_artist=line_input,  
                                                    output_path = "./", # need to comment later
                                                    radius_set=[int(radius)], percentiles=[0],
                                                    )

    # resize simplified line to original size
    line_simplify = line_simplify.resize(line_input.size)
    # line_simplify = cv2.resize(line_simplify, line_artist.size, interpolation = cv2.INTER_NEAREST)

    # color fill map for visualize
    drop_small_regions(fill_map_artist)
    fill_map_artist = verify_reigon(fill_map_artist, True)
    fill_artist, palette = show_fillmap_auto(fill_map_artist)

    fill, palette = show_fillmap_auto(fill_map, palette)
    
    # get layers, we don't need layers right now
    # layers = get_layers(fill_map, palette)
    # layers_artist = get_layers(fill_map_artist, palette)

    # refine the neural line
    
    line_simplify = fillmap_masked_line(fill_map, line_input)

    # add alpha channel back to line arts
    line_simplify = add_alpha(line_simplify, line_color = "9ae42c")
    line_artist = add_alpha(line_artist)

    

    return {
        'line_artist': line_artist,
        'line_simplified': line_simplify,
        'fill_color': fill,
        'fill_integer': fill_map,
        # 'layers': layers,
        'components_color': fill_artist,
        'components_integer': fill_map_artist,
        # 'components_layers': layers_artist,
        'palette': palette
        }

def run_multiple(line_artist_list, net_list, radius_list, preview=False):
    '''
    Given:
        line_artist_list, a list of artist line art, now we assume it will always be numpy array
        net, the name of model
        radius, the radius for trapped ball filling
    Return:
        result lists
    '''
    assert len(line_artist_list) == len(net_list)
    assert len(net_list) == len(radius_list)

    line_sim_list = []
    fill_list = []
    fill_map_list = []
    # layers_list = []
    fill_artist_list = []
    fill_map_artist_list = []
    # layers_artist_list = []
    palette_list = []

    for i in range(len(line_artist_list)):
        if preview:
            result = run_single(line_artist_list[i], net_list[i], radius_list[i], preview=True)
            fill_list.append(result)

        else:
            results = run_single(line_artist_list[i], net_list[i], radius_list[i])

            line_sim_list.append(results['line_simplified'])
            fill_list.append(results['fill_color'])
            fill_map_list.append(results['fill_integer'])
            # layers_list.append(results['layers'])
            fill_artist_list.append(results['components_color'])
            fill_map_artist_list.append(results['components_integer'])
            # layers_artist_list.append(results['components_layers'])
            palette_list.append(results['palette'])
    
    return {
        'line_simplified': line_sim_list,
        'fill_color': fill_list,
        'fill_integer': fill_map_list,
        # 'layers': layers_list,
        'components_color': fill_artist_list,
        'components_integer': fill_map_artist_list,
        # 'components_layers': layers_artist_list
        'palettes': palette_list
        }

def merge(fill_map, merge_map, palette):
    '''
    Given:
        fill_map, labeled region map
        merge_map, a image contains merge stroke only
    Action:
        merge all selected region to the largest one
    '''
    # get labels selected by merge stroke
    print("Log:\tmerging")
    merge_labels = stroke_to_label(fill_map, merge_map)
    if len(merge_labels) <= 1:
        print("Log:\t(probably) inaccurate input, skip merge")
        fill, palette = show_fillmap_auto(fill_map, palette)
        layers = get_layers(fill_map, palette)
        return {"fill_color": fill,
                "fill_integer": fill_map,
                "layers": layers,
                "palette": palette}

    # find max region
    max_label = find_max_region(fill_map, merge_labels)

    # merge all rest regions to max region
    for r in merge_labels:
        if r == max_label: continue
        mask = fill_map == r
        fill_map[mask] = max_label

    # visualize fill_map
    fill, palette = show_fillmap_auto(fill_map, palette)
    layers = get_layers(fill_map, palette)
    
    return {"fill_color": fill,
            "fill_integer": fill_map,
            "layers": layers,
            "palette": palette}

def split_auto(fill_map, fill_map_artist, split_map_auto, artist_line, palette):
    '''
    Given:
        fill_map, labeled final region map 
        fill_map_artist, labeled region on artist line only, 
            this will contain much more regions than the final fill map
        split_map_auto, a image contains split stroke only
    Action:
        split new regions into fill_map
    '''
    # preprocessing lines
    artist_line = add_white(artist_line, return_numpy = True)

    # select regions that user want to split
    print("Log:\tcoarse splitting")
    split_labels_artist = stroke_to_label(fill_map_artist, split_map_auto)
    if len(split_labels_artist) <= 1:
        print("Log:\t(probably) inaccurate input, skip split auto")
        neural_line = fillmap_masked_line(fill_map, artist_line)
        artist_line = add_alpha(Image.fromarray(artist_line))
        neural_line = add_alpha(neural_line, line_color = "9ae42c")
        fill, palette = show_fillmap_auto(fill_map, palette)
        layers = get_layers(fill_map, palette)
        return {"line_artist": artist_line,
                "line_neural": neural_line,
                "fill_color": fill,
                "fill_integer": fill_map,
                "layers": layers,
                "palette": palette}

    # find out the region that don't needs to be extract
    neural_to_artist = {} # map from fill_map to fill_map_artist
    for r in split_labels_artist:
        rn = np.unique(fill_map[fill_map_artist == r])
        for s in rn:
            if s in neural_to_artist:
                neural_to_artist[s].append(r)
            else:
                neural_to_artist[s] = [r]
    fixed_region = []
    for s in neural_to_artist.values():
        if len(s) > 1:
            fixed_region.append(find_max_region(fill_map_artist, s))

    # split rest regions
    next_label = np.max(fill_map) + 1
    for r in split_labels_artist:
        if r in fixed_region: continue
        mask = fill_map_artist == r
        fill_map[mask] = next_label
        next_label += 1

    # update neural line
    neural_line = fillmap_masked_line(fill_map, artist_line)

    # visualize fill_map and lines
    fill, palette = show_fillmap_auto(fill_map, palette)
    layers = get_layers(fill_map, palette)
    artist_line = add_alpha(Image.fromarray(artist_line))
    neural_line = add_alpha(neural_line, line_color = "9ae42c")

    return {"line_artist": artist_line,
            "line_neural": neural_line,
            "fill_color": fill,
            "fill_integer": fill_map,
            "layers": layers,
            "palette": palette}

def split_manual(fill_map, fill_map_artist, split_map_manual, artist_line, neural_line, palette):
    '''
    Given:
        fill_map, labeled final region map 
        fill_map_artist, labeled region on artist line
        split_map_manual, a image contains manual split stroke only, it should be precise
    Action:
        split new regions into fill_map
    '''
    print("Log:\tfine splitting")

    artist_line = add_white(artist_line, return_numpy = True)
    neural_line = add_white(neural_line, return_numpy = True)

    # convert split map to grayscale
    if len(split_map_manual.shape) == 3:
        split_map_manual = cv2.cvtColor(split_map_manual, cv2.COLOR_BGR2GRAY)

    # merge user modify to lines
    artist_line[split_map_manual < 240] = 0
    neural_line[split_map_manual < 240] = 0

    # find the region need to be split on artist fill map
    split_labels = stroke_to_label(fill_map_artist, split_map_manual)
    if len(split_labels) == 0:
        print("Log:\t(probably) inaccurate input, skip split manual")
        artist_line = add_alpha(artist_line)
        neural_line = add_alpha(neural_line, line_color = "9ae42c")
        fill, palette = show_fillmap_auto(fill_map, palette)
        layers = get_layers(fill_map, palette)
        return {"line_artist": artist_line,
                "line_neural": neural_line,
                "fill_color": fill,
                "fill_integer": fill_map,
                "layers": layers,
                "palette": palette}

    # merge all involved regions
    p_list = []
    for r in split_labels:
        p_list.append(np.where(fill_map_artist == r))
    merged_mask = merge_points(p_list)
    label_old = find_region(fill_map, merged_mask)

    # split  
    masks = []
    split_single_region = np.zeros(fill_map.shape, dtype=np.uint8)
    split_single_region[merged_mask] = 1
    split_single_region[artist_line < 240] = 0
    _, split_regions = cv2.connectedComponents(split_single_region, connectivity=8)
    regions = np.unique(split_regions)
    regions = regions[regions != 0]
    if len(regions) > 1:
        max_region = find_max_region(split_regions, regions)
        for s in regions:
            if s == max_region: 
                mask_old = split_regions == s
            else:
                masks.append(split_regions == s)

    # split regions
    next_label = fill_map.max() + 1
    for mask in masks:
        if is_split_safe(fill_map, mask):
            fill_map[mask] = next_label
            next_label += 1
    fill_map[mask_old] = label_old
    fill_map[split_map_manual < 240] = label_old

    # visualize fill_map
    fill, palette = show_fillmap_auto(fill_map, palette)
    layers = get_layers(fill_map, palette)
    artist_line = add_alpha(Image.fromarray(artist_line))
    neural_line = add_alpha(Image.fromarray(neural_line), line_color = "9ae42c")

    return {"line_artist": artist_line,
            "line_neural": neural_line,
            "fill_color": fill,
            "fill_integer": fill_map,
            "layers": layers,
            "palette": palette}

def show_fillmap_manual(fill_map, palette):
    '''
        Given:
            fill_map, the labeled region map
        return:
            color_map, the random colorized map
    '''
    region_num = np.max(fill_map) + 1
    
    if region_num > len(palette):
        print("Warning:\tfind unmatched fill map and color palette, please stop and debug the server")
        p_increment = np.random.randint(0, 255, (region_num - len(palette), 3), dtype=np.uint8)
        palette = np.concatenate((palette, p_increment), axis = 0)

    return {"fill_color": palette[fill_map], 
            "palette": palette}

def show_fillmap_auto(fill_map, palette=None):
    '''
    Given:
        fill_map, the labeled region map
        palette, the color palette
    return:
        color_map, the random colorized map
    '''
    region_num = np.max(fill_map) + 1
    
    if palette is None:
        palette = init_palette(region_num + 50)

    if region_num > len(palette):
        print("Warning:\tgot region numbers greater than color palette size, which is unusual, please check your if filling result is correct")
        palette = init_palette(region_num)

    return palette[fill_map].astype(np.uint8), palette

def drop_small_regions(fill_map, th=0.000005):
    h, w = fill_map.shape
    th = int(h*w*th)
    labels = np.unique(fill_map)

    counter = 0
    for r in labels:
        mask = fill_map == r
        if mask.sum() < th:
            fill_map[mask] = 0
            counter += 1
    print("Log:\t%d region that smaller than %d pixels are removed"%(counter, th))

def get_layers(fill_map, palette):
    '''
    Given:
        fill_map, the labeled region map
    Return:
        layers, a list of numpy arrays, each array is a single region
    '''
    h, w = fill_map.shape
    layers = []

    labels = np.unique(fill_map)
    # assert np.max(fill_map) + 1 == len(labels)
    assert len(labels) <= len(palette)

    for region in labels:

        layer = np.ones((h, w, 3), dtype=np.uint8) * 255
        mask = fill_map == region
        layer[mask] = palette[region]
        # layer = add_alpha(Image.fromarray(layer))
        layers.append(layer)

    return layers

def init_palette(color_num = 100):
    '''
    Initialize the auto color palette, assume there will be no more than 500 regions
    If we get a fill map more than 100 regions, then we need to re-initialize this with larger number
    '''
    fixed = ["#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a",
            "#d62728", "#ff9896", "#9467bd", "#c5b0d5", "#8c564b", "#c49c94", 
            "#e377c2", "#f7b6d2", "#7f7f7f", "#c7c7c7", "#bcbd22", "#dbdb8d",
            "#17becf", "#9edae5"]
    
    # convert hex color table to int 
    for i in range(len(fixed)):
        assert len(fixed[i]) == 7
        fixed[i] = fixed[i].replace("#", "")
        color = []
        for j in range(0, len(fixed[i]), 2):
            color.append(int(fixed[i][j:j+2], 16))
        fixed[i] = color
    fixed = np.array(fixed, dtype = np.uint8)

    palette = np.random.randint(0, 255, (color_num, 3), dtype=np.uint8) 
    palette[0] = [0, 0, 0]
    palette[1:21] = fixed

    return palette

def stroke_to_label(fill_map, stroke_map):
    '''
    Given:
        fill_map, labeled region map
        merge_map, a image contains stroke only, assume it is image stored as numpy array
    Return:
        the region index of which are selected by stroke map
    '''
    # threshold the stroke map
    if len(stroke_map.shape) == 3:
        stroke_map = cv2.cvtColor(stroke_map, cv2.COLOR_BGR2GRAY)
    stroke_map = stroke_map.copy()
    stroke_map[stroke_map < 240] = 0
    stroke_map[stroke_map >= 240] = 1

    # get the labels selected by stroke map
    labels = np.unique(fill_map[stroke_map == 0])
    labels = labels[labels != 0]

    return labels

def display_region(fill_map, region):
    '''
    A helper function that visualize a given region
    '''
    r = (fill_map == region).astype(np.uint8)*255
    Image.fromarray(r).show()

def find_region(fill_map, mask):
    '''
    A helper function to find the most possible region in mask
    '''
    labels, count = np.unique(fill_map[mask], return_counts=True)
    labels = labels[labels != 0]

    return labels[np.argsort(count)[-1]]

def find_max_region(fill_map, selected_labels):
    '''
    A helper function to find the label of max region amout selected regions
    '''
    # find the size of selected regions
    labels, counts = np.unique(fill_map, return_counts=True)
    labels_sorted = labels[np.argsort(counts)]

    max_idx = -1
    for r in selected_labels:
        if max_idx == -1:
            max_idx = np.where(labels_sorted == r)
        else:
            cur_idx = np.where(labels_sorted == r)
            if max_idx < cur_idx:
                max_idx = cur_idx
    max_label = labels_sorted[max_idx]

    return max_label

def is_split_safe(fill_map, mask, th=0.9):
    '''
    A helper function that to test if the given region could be splited safely
        if the major region in the given have less than th% of mask area (size)
        then it should not be splited.
    '''
    labels, counts = np.unique(fill_map[mask], return_counts=True)
    if counts.max() / counts.sum() < th:
        return False
    else:
        return True

def merge_points(points_list):
    '''
    A helper function for merge masks
    '''
    for i in range(len(points_list)):
        points_list[i] = np.array(points_list[i])

    points_merge = np.concatenate(points_list, axis = -1)

    return tuple(points_merge)

def save_np(array, path):
    '''
    A helper function to save numpy array, for debug purpose
    '''
    with open(path, 'wb') as f:
        np.save(f, array)

def load_np(path):
    '''
    A helper function to load numpy array, for debug purpose
    '''
    print('Log:\tload %s'%path)
    with open(path, 'rb') as f:
        result = np.load(f)
    return result

def test_case1():
    import os
    
    fill_map = load_np("./trapped_ball/examples/01_fill_integer.npy")
    fill_map_artist = load_np("./trapped_ball/examples/01_components_integer.npy")
    fill_map = thinning(fill_map)
    fill_map_artist = thinning(fill_map_artist)

    line_artist = Image.open("./trapped_ball/examples/01.png")
    # line_neural = Image.open("./trapped_ball/examples/01_sim.png")
    # line_neural = line_neural.resize(line_artist.size)
    # line_neural = fillmap_masked_line(fill_map, line_artist)
    # line_neural = add_alpha(line_neural, line_color = "9ae42c")
    # Image.fromarray(line_neural).save("11.png")

    palette = init_palette(100)

    # merge
    merge_map = np.array(Image.open("./trapped_ball/examples/01_merge_test01.png").convert("L"))
    result = merge(fill_map, merge_map, palette)
    print("Done")
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    # merge
    merge_map = np.array(Image.open("./trapped_ball/examples/01_merge_test02.png").convert("L"))
    result = merge(fill_map, merge_map, palette)
    print("Done")
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    # split_auto
    split_map_auto = Image.open("./trapped_ball/examples/01_split_auto_test01.png")
    split_map_auto = add_white(split_map_auto).convert("L")
    split_map_auto = np.array(split_map_auto)

    result = split_auto(fill_map, fill_map_artist, split_map_auto, line_artist, palette)
    print("Done")
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    # merge
    merge_map = np.array(Image.open("./trapped_ball/examples/01_merge_test03.png").convert("L"))
    result = merge(fill_map, merge_map, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    # merge
    merge_map = np.array(Image.open("./trapped_ball/examples/01_merge_test04.png").convert("L"))
    result = merge(fill_map, merge_map, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    print("Done")

def test_case2():
    import os
    
    fill_map = load_np("./trapped_ball/examples/02_fill_integer.npy")
    fill_map_artist = load_np("./trapped_ball/examples/02_components_integer.npy")
    # artist_line = np.array(Image.open("./trapped_ball/examples/02.png").convert("L"))
    palette = init_palette(100)

    # split manual
    split_map_manual = np.array(Image.open("./trapped_ball/examples/02_split_manual_test01.png").convert("L"))
    result = split_manual(fill_map, fill_map_artist, split_map_manual, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    # split manual
    split_map_manual = np.array(Image.open("./trapped_ball/examples/02_split_manual_test02.png").convert("L"))
    result = split_manual(fill_map, fill_map_artist, split_map_manual, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    # split auto
    split_map_auto = np.array(Image.open("./trapped_ball/examples/02_split_auto_test01.png").convert("L"))
    result = split_auto(fill_map, fill_map_artist, split_map_auto, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    # split auto
    split_map_auto = np.array(Image.open("./trapped_ball/examples/02_split_auto_test02.png").convert("L"))
    result = split_auto(fill_map, fill_map_artist, split_map_auto, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")    

    # split auto
    split_map_auto = np.array(Image.open("./trapped_ball/examples/02_split_auto_test03.png").convert("L"))
    result = split_auto(fill_map, fill_map_artist, split_map_auto, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")    

    # merge
    merge_map = np.array(Image.open("./trapped_ball/examples/02_merge_test01.png").convert("L"))
    result = merge(fill_map, merge_map, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    merge_map = np.array(Image.open("./trapped_ball/examples/02_merge_test02.png").convert("L"))
    result = merge(fill_map, merge_map, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    merge_map = np.array(Image.open("./trapped_ball/examples/02_merge_test03.png").convert("L"))
    result = merge(fill_map, merge_map, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    merge_map = np.array(Image.open("./trapped_ball/examples/02_merge_test04.png").convert("L"))
    result = merge(fill_map, merge_map, palette)
    fill = result['fill_color']
    Image.fromarray(fill).show()
    os.system("pause")

    print("Done")

# for debug
if __name__ == "__main__":
    
    '''
    test for initial work flow
    '''
    # line_path = "./trapped_ball/examples/02.png"
    # line_artist = Image.open(line_path).convert("L")
    # initial_nets()
    # results = run_single(line_artist, "512", 1)
    
    '''
    test for merge
    '''
    test_case1()
    
    '''
    test for auto split and manual split
    '''
    # test_case2()
