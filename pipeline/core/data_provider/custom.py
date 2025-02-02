import numpy as np
import torch
import random
import zipfile
import threading
import gc
import uuid
import logging

logging.basicConfig(filename="data_provider.log",
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.DEBUG)

logger = logging.getLogger('CDP')
# logger.setLevel(logging.CRITICAL) # to disable logging

def get_shape(path):
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith('input_raw_data.npy'):
                npy = archive.open(name)
                version = np.lib.format.read_magic(npy)
                shape, fortran, dtype = np.lib.format._read_array_header(npy, version)
                break
    return shape



class DataUnit:
    def __init__(self, paths, shapes, prefetch_size, img_channel1, img_layers, total_length, max_batches):
        self.cpath = None
        self.paths = paths
        self.shapes = shapes
        self.prefetch_size = prefetch_size
        self.img_channel1 = img_channel1
        self.img_layers = img_layers
        self.total_length = total_length
        self.max_batches = max_batches
        self.id = str(uuid.uuid4())[:4]
        
        
        # note last batch is skipped
        self.dsize = (prefetch_size+1) * total_length 
        self.base_start_index = 0
        logger.info(f"DataUnit {self.id} created with size: {self.dsize}")
        self.data = torch.empty((self.dsize, img_channel1, shapes[0][2], shapes[0][3]), dtype=torch.float32)
        self.start_index = self.base_start_index
        self.up_index = -total_length # update index (for the next batch)
        self.recently_allocated = False
        
        
        
        
    def get_index(self, gpu_index=0):
        # logger.info(f"max_batches: {self.max_batches}, gpu_index: {gpu_index}, start_index: {self.start_index}")
        return (self.start_index + gpu_index) % self.max_batches # this is data index, for a gpu index < max_batches.
        
    def connect(self,i):
        # connect data unit to a particular file
        self.cpath=self.paths[i]
        self.clpath=self.cpath.split('/')[-2][:12]
        logger.info(f"\tDataUnit {self.id} connected to {self.clpath} or index {i}")
    
    def allocate(self, k):
        # prefetch all at once, starting from image k... (gpu_index is set to 0 at this point)
        self.start_index = k
        fdata = np.flip(np.load(self.cpath, mmap_mode='r')["input_raw_data"][k:k+self.dsize, self.img_layers, :, :],axis=0).copy() # not sure why flip is needed, but it is
        self.data = torch.from_numpy(
            fdata
            ).to(torch.float32)
        logger.info(f"\tDataUnit {self.id} allocated from {self.clpath}, with start_index {self.start_index}")
        self.recently_allocated = True
        
        gc.collect()
        
    def update(self, gpu_index):
        if not self.recently_allocated:
        
            save_index = self.start_index
            
            # move start_index
            self.start_index += self.total_length
            self.start_index %= self.max_batches
            
            # update data unit with new data, starting from image gpu_index... when gpu_index % total_length == 0 and this is not immediately after allocate
            set_index = gpu_index
            cu_index = self.get_index(gpu_index + self.total_length)
            # torch.roll(self.data,set_index,dims=0)[:self.total_length] = torch.from_numpy(
            #     np.roll(np.load(self.cpath, mmap_mode='r')["input_raw_data"],cu_index,axis=0)[:self.total_length, self.img_layers, :, :]
            #     ).to(torch.float32)
            
            rolled = torch.from_numpy(
                np.flip(np.roll(np.load(self.cpath, mmap_mode='r')["input_raw_data"],-(cu_index),axis=0),axis=0)[:self.total_length, self.img_layers, :, :]
                ).to(torch.float32)
            
            a = set_index
            b = (set_index + self.total_length) % self.dsize
            if b < a:
                c = self.dsize - a
                self.data[a:] = rolled[:c]
                self.data[:b] = rolled[c:]
            else: self.data[a:b] = rolled


            
            logger.info(f"\tDataUnit {self.id}: ({set_index}:{(self.total_length+set_index) % self.dsize}) updated from {self.clpath}: ({cu_index}:{cu_index+self.total_length})")
            
            # # move start index back to current image
            # if self.recently_allocated:
            #     self.recently_allocated = False
            #     self.start_index -= self.total_length
            # else:
            self.start_index = save_index
                
            logger.debug(f"gpu_index {gpu_index}, self.dsize {self.dsize}")    
            if gpu_index == self.dsize-self.total_length:
                self.start_index += self.dsize
        else:
            self.recently_allocated = False
        
        
    def get(self, gpu_index):
        
        # if at end (gpu_index == self.max_batches - self.total_length), we need to reallocate at 0-index
        if (self.start_index==self.max_batches - self.total_length):
            self.allocate(self.base_start_index) # start over
        
        # get data unit, starting from image gpu_index... when gpu_index % total_length == 0
        logger.info(f"\tDataUnit {self.id} GET from buffer:{gpu_index}:{(self.total_length+gpu_index) % self.dsize} or {self.clpath}:{self.get_index(gpu_index)}:{self.get_index(gpu_index)+self.total_length}")
        return torch.roll(self.data,gpu_index,dims=0)[:self.total_length]
        

def make_valid(paths):
    logger.info("*************************************************")
    logger.info(f"Making valid paths from {paths}")
    cp = []
    for i in range(len(paths)):
        if paths[i].endswith('.npz'):
            try:
                get_shape(paths[i])
            except:
                pass
            else:
                cp.append(paths[i])
    logger.info(f"Valid paths: {cp}")
    logger.info("*************************************************")
    return cp


class DataBatch(torch.utils.data.Dataset):
    def __init__(self, name, paths, total_length, img_channel1, img_layers, prefetch_size, batch_size, testing):
        self.paths = make_valid(paths)
        self.total_length = total_length
        self.img_channel1 = img_channel1
        self.img_layers = img_layers
        self.batch_size = batch_size
        self.prefetch_size = prefetch_size
        self.name = name
        
        self.load()
        
        # odd issue with first batch, we will skip it
        
        self.dsize = (prefetch_size+1) * total_length # total size of data unit
        self.base_start_index = 0
        if testing:
            logger.info("Testing, setting batch size to match number of paths")
            self.batch_size = len(self.paths)
            self.path_index = 0
        self.testing = testing
        self.ordered_testing = False
        # if self.batch_size > len(self.paths):
        #     logger.warning(f"Batch size {self.batch_size} must be less than number of paths {len(self.paths)}")
        #     self.batch_size = len(self.paths)
        
        # shape data is [frame, channel, height, width]
        self.max_batches = min([s[0] for s in self.shapes]) - self.total_length -1# exclusive
        self.units = [DataUnit(paths, self.shapes, prefetch_size, img_channel1, img_layers, total_length, self.max_batches) for _ in range(self.batch_size)]
        
        self.total = self.max_batches * len(self.paths)
        
        self.unit_selector = 0
        self.gpu_index = 0 # step isethe current step in each batch of size 1080 or so, gpu_index is that mod dataunit size. Note the local gpu_index will change for dataunits, since that will be modded to get the current batch from whichever location.
        self.step = 0
        self.threads = []
        
    def reset_for_full_test(self):
        self.path_index = 0
        self.ordered_testing = True
        self.unit_selector = 0
        self.gpu_index = 0
        self.step = 0
        self.threads = []    
        
    def __len__(self):
        return self.max_batches
    
    def get(self, dummy_index):        
        # get unit
        unit = self.units[self.unit_selector]
        self.unit_selector = (self.unit_selector + 1) % self.batch_size
        
        # connect and allocate if starting new dataset
        if self.step == 0:
            # get index
            # logger.info(self.paths)
            logger.info(f"High = {len(self.paths)}")
            if self.ordered_testing:
                index = self.path_index
                self.path_index = (self.path_index + 1) % len(self.paths)
            else:
                index = torch.randint(low=0, high=len(self.paths), size=(1,)).item()
            # TODO make striated (skip used indices)
            
            unit.connect(index)
            
            # unit.allocate(self.base_start_index) # need to randomize this if not testing
            
            if self.ordered_testing:
                unit.allocate(self.base_start_index)
            else:
                unit.allocate(torch.randint(low=0, high=self.max_batches, size=(1,)).item())
            out = unit.get(self.gpu_index) # discard first batch
        else:
            out = unit.get(self.gpu_index)
            
        # step after all units (every batch)
        if self.unit_selector == 0:
            self.gpu_index = (self.gpu_index + 1) % (self.total_length * (self.prefetch_size+1))
            self.step = (self.step + 1) % self.max_batches
            logger.info(f"Step {self.step} of {self.max_batches}")
        
        # update after every thread (every batch, every unit)
        if self.gpu_index % self.total_length == 0 and self.step != 0:
            # print(self.gpu_index // self.total_length + 1)
            # async updating
            logger.info(f"Starting update thread {self.gpu_index // self.total_length + 1}")
            t = threading.Thread(target=unit.update, args=((self.gpu_index - self.total_length) % (self.total_length*(self.prefetch_size+1)),) )
            t.start()
            self.threads.append(t)
            
            
        # wait for update after last thread (last batch, last unit)    
        if self.unit_selector == len(self.units) - 1:    
            if len(self.threads) == self.prefetch_size * self.batch_size:
                # wait for all updates to finish before re-entering loop
                for t in self.threads:
                    t.join()
                self.threads = []
                gc.collect()
                logger.info(f"Finished update thread {self.gpu_index // self.total_length}")
            
        
        return out
    
    def __getitem__(self, dummy_index):
        if self.step ==0:
            self.get(dummy_index) # discard first batch
        return self.get(dummy_index)
        
    def load(self):
        print(f"{self.name}, Loading data from {self.paths}")
        
        self.shapes = [get_shape(p) for p in self.paths]
        self.lengths = [s[0] for s in self.shapes]
        self.starts = np.cumsum(self.lengths)
        
    

class InputHandle:
    def __init__(self, input_param):
        self.paths = input_param['paths']
        self.num_paths = len(input_param['paths'])
        self.name = input_param['name']
        self.input_data_type = input_param.get('input_data_type', 'float32')
        self.output_data_type = input_param.get('output_data_type', 'float32')
        self.batch_size = input_param['minibatch_size']
        self.is_output_sequence = input_param['is_output_sequence']
        self.concurent_step = input_param['concurent_step']
        self.img_layers = input_param['img_layers']
        if input_param['is_WV']:
            # print(f"input_param['img_channel']: {input_param['img_channel']}")
            self.img_channel1 = int(input_param['img_channel']/10.)
        else:
            self.img_channel1 = input_param['img_channel']

        self.total_length = input_param['total_length']
        self.prefetch_size = input_param.get('prefetch_size', 1) # holds CPU pinned memory of size prefetch+1 x a single GPU minibatch (timeseries sample) per DataUnit
        
        testing = input_param.get('testing', False)
        
        self.dataset = DataBatch(self.name, self.paths, self.total_length, self.img_channel1, self.img_layers, self.prefetch_size, self.batch_size, testing)       
        
    def get_max_batches(self):
        return self.dataset.max_batches
    
    def reset_for_full_test(self):
        self.dataset.reset_for_full_test()

    def total(self):
        return self.dataset.total

    def begin(self, do_shuffle=True):
        self.dataloader = torch.utils.data.DataLoader(self.dataset, batch_size = self.dataset.batch_size, shuffle = do_shuffle)

    def next(self):
        pass

    def no_batch_left(self):
        return self.dataset.step == 0

    def get_batch(self):
        return next(iter(self.dataloader))
