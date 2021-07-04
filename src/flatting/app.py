from aiohttp import web
from PIL import Image
from io import BytesIO
from datetime import datetime
from os.path import join, exists

import numpy as np
from . import flatting_api
from . import flatting_api_async
import base64
import os
import io
import json
import asyncio
import multiprocessing

MULTIPROCESS = False
LOG = True

routes = web.RouteTableDef()

@routes.get('/')
# seems the function name is not that important?
async def hello(request):
    return web.Response(text="Flatting API server is running")

## Add more API entry points
@routes.post('/flatsingle')
async def flatsingle( request ):
    data = await request.json()
    try:
        data = json.loads(data)
    except:
        print("got dict directly")
    
    # convert to json
    img = to_pil(data['image'])
    net = str(data['net'])
    radii = int(data['radius'])
    resize = data['resize']
    if 'userName' in data:
        user = data['userName']
    img_name = data['fileName']
    if resize:
        w_new, h_new = data["newSize"]
    else:
        w_new = None
        h_new = None

    if MULTIPROCESS:
        flatted = await flatting_api_async.run_single(img, net, radii, resize, w_new, h_new)
    else:
        flatted = flatting_api.run_single(img, net, radii, resize, w_new, h_new)

    result = {}
    result['line_artist'] = to_base64(flatted['line_artist'])
    result['line_hint'] = to_base64(flatted['line_hint'])
    result['line_simplified'] = to_base64(flatted['line_simplified'])
    result['image'] = to_base64(flatted['fill_color'])
    result['fill_artist'] = to_base64(flatted['components_color'])
    
    if LOG:
        now = datetime.now()
        save_to_log(now, flatted['line_artist'], user, img_name, "line_artist", "flat")
        save_to_log(now, flatted['line_hint'], user, img_name, "line_hint", "flat")
        save_to_log(now, flatted['line_simplified'], user, img_name, "line_simplified", "flat")
        save_to_log(now, flatted['fill_color'], user, img_name, "fill_color", "flat")
        save_to_log(now, flatted['components_color'], user, img_name, "fill_color_floodfill", "flat")
        save_to_log(now, flatted['fill_color_neural'], user, img_name, "fill_color_neural", "flat")
        save_to_log(now, flatted['line_neural'], user, img_name, "line_neural", "flat")
        print("Log:\tlogs saved")
    return web.json_response( result )
                
@routes.post('/merge')
async def merge( request ):
    data = await request.json()
    try:
        data = json.loads(data)
    except:
        print("got dict directly")

    line_artist = to_pil(data['line_artist'])
    fill_neural = np.array(to_pil(data['fill_neural']))
    fill_artist = np.array(to_pil(data['fill_artist']))
    stroke = to_pil(data['stroke'])
    if 'userName' in data:
        user = data['userName']
    img_name = data['fileName']
    # palette = np.array(data['palette'])
    
    if MULTIPROCESS:
        merged = await flatting_api_async.merge(fill_neural, fill_artist, stroke, line_artist)
    else:
        merged = flatting_api.merge(fill_neural, fill_artist, stroke, line_artist)

    result = {}
    result['image'] = to_base64(merged['fill_color'])
    result['line_simplified'] = to_base64(merged['line_simplified'])
    if LOG:
        now = datetime.now()
        save_to_log(now, merged['line_simplified'], user, img_name, "line_simplified", "merge")
        save_to_log(now, merged['fill_color'], user, img_name, "fill_color", "merge")
        save_to_log(now, stroke, user, img_name, "merge_stroke", "merge")
        save_to_log(now, fill_artist, user, img_name, "fill_color_floodfill", "merge")
        print("Log:\tlogs saved")

    return web.json_response(result)

@routes.post('/splitmanual')
async def split_manual( request ):
    data = await request.json()
    try:
        data = json.loads(data)
    except:
        print("got dict directly")
    
    fill_neural = np.array(to_pil(data['fill_neural']))
    fill_artist = np.array(to_pil(data['fill_artist']))
    stroke = np.array(to_pil(data['stroke']))
    line_artist = to_pil(data['line_artist'])
    fix_neural = data['mode']
    if 'userName' in data:
        user = data['userName']
    img_name = data['fileName']
    
    if MULTIPROCESS:
        splited = await flatting_api_async.split_manual(fill_neural, fill_artist, stroke, line_artist, fix_neural)
    else:
        splited = flatting_api.split_manual(fill_neural, fill_artist, stroke, line_artist, fix_neural)

    result = {}
    result['line_artist'] = to_base64(splited['line_artist'])
    result['line_simplified'] = to_base64(splited['line_neural'])
    result['image'] = to_base64(splited['fill_color'])
    result['fill_artist'] = to_base64(splited['fill_artist'])
    result['line_hint'] = to_base64(splited['line_hint'])

    if LOG:
        now = datetime.now()
        save_to_log(now, splited['line_neural'], user, img_name, "line_simplified", "split_%s"%str(fix_neural))
        save_to_log(now, splited['line_artist'], user, img_name, "line_artist", "split_%s"%str(fix_neural))
        save_to_log(now, splited['fill_color'], user, img_name, "fill_color", "split_%s"%str(fix_neural))
        save_to_log(now, stroke, user, img_name, "split_stroke", "split_%s"%str(fix_neural))
        save_to_log(now, splited['fill_artist'], user, img_name, "fill_color_floodfill", "split_%s"%str(fix_neural))
        save_to_log(now, splited['line_hint'], user, img_name, "line_hint", "split_%s"%str(fix_neural))
        print("Log:\tlogs saved")
    return web.json_response(result)    

@routes.post('/showfillmap')
async def show_fillmap_manual( request ):
    data = await request.json()
    data = json.loads(data)

    img = to_pil(data['image'])
    palette = np.array(data['palette'])

    fill_color = flatting_api.show_fillmap_manual(img, palette)

    result = {}
    result["image"] = to_base64(fill_color["fill_color"])
    result["palette"] = fill_color["palette"].tolist()

    return web.json_response(result)

def to_base64(array):
    '''
    A helper function to convert numpy array to png in base64 format
    '''
    with io.BytesIO() as output:
        if type(array) == np.ndarray:
            Image.fromarray(array).save(output, format='png')
        else:
            array.save(output, format='png')
        img = output.getvalue()
    img = base64.encodebytes(img).decode("utf-8")
    return img

def to_pil(byte):
    '''
    A helper function to convert byte png to PIL.Image
    '''
    byte = base64.b64decode(byte)
    return Image.open(BytesIO(byte))

def save_to_log(date, data, user, img_name, save_name, op):
    save_folder = "[%s][%s][%s_%s]"%(user, str(date.strftime("%b-%m-%Y %H-%M-%S")), img_name, op)
    save_folder = join("./logs", save_folder)
    if exists(save_folder) == False:
        os.makedirs(save_folder)
    try:
        if type(data) == np.ndarray:
            Image.fromarray(data).save(join(save_folder, "%s.png"%save_name))
        else:
            data.save(join(save_folder, "%s.png"%save_name))
    except:
        print("Warning:\tsave log failed!")

def main():
    app = web.Application(client_max_size = 1024 * 1024 ** 2)
    app.add_routes(routes)
    web.run_app(app)
    
    ## From JavaScript:
    # let result = await fetch( url_of_server.py, { method: 'POST', body: JSON.stringify(data) } ).json();

if __name__ == '__main__':
    main()
