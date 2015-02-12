"""
    The CellH5 Project
    Copyright (c) 2012 - 2015 Christoph Sommer
    Gerlich Lab, IMBA Vienna, Huber Lab, EMBL Heidelberg
    www.cellh5.org

    CellH5 is distributed under the LGPL License.
    See LICENSE.txt for details.
    See AUTHORS.txt for author contributions.
"""

import sys
import os
import numpy
import h5py
import pandas
import matplotlib.pyplot as plt

import unittest
import functools
import collections

from itertools import chain, izip
from collections import OrderedDict
from contextlib import contextmanager

import cellh5
from cellh5 import CH5PositionCoordinate, CH5Const

import logging

log = logging.getLogger(__name__)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
log.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
log.addHandler(ch)


class CH5PositionDescription(object):
    def __init__(self):
        self.values = []
        
    def add_row(self, **kwargs):
        self.values.append(kwargs)
        
    def __len__(self):
        return len(self.values)
    
    fields = []
    def ro_recarray(self):
        array = []
        for r in range(len(self)):
            row = []
            for f in self.fields:
                if f in self.values[r]: 
                    row.append(self.values[r][f])
                else:
                    row.append(None)
                    
            array.append(tuple(row))
            
        recarray = numpy.array(array, dtype=self.dtype)
        
        return recarray 
                

class CH5ImageChannelDefinition(CH5PositionDescription):
    fields = ['channel_name', 'description', 'is_physical', 'voxel_size', 'color']
    dtype = numpy.dtype([('channel_name', '|S50'),
                             ('description', '|S100'),
                             ('is_physical', bool),
                             ('voxel_size', 'float', 3),
                             ('color', "|S7")])
    def __init__(self):
        super(CH5ImageChannelDefinition, self).__init__()
      
class CH5ImageRegionDefinition(CH5PositionDescription):
    fields = ["region_name", "channel_idx"]
    dtype = numpy.dtype([('region_name', '|S50'), ('channel_idx', 'i')])
    def __init__(self):
        super(CH5ImageRegionDefinition, self).__init__()
        

class CH5FileWriter(cellh5.CH5File):
    def __init__(self, filename, sister_file=None):
        self.filename = filename
        self._f = h5py.File(filename, "w")
        self._init_basic_structure()
        self._file_handle = self._f
        
    def _init_basic_structure(self):
        # create basic definition
        def_grp = self._f.create_group(CH5Const.DEFINITION)
        for grp in [CH5Const.IMAGE, CH5Const.OBJECT, CH5Const.FEATURE]:
            def_grp.create_group(grp)
            
        self._f.create_group(CH5Const.PREFIX)
        
    def add_position(self, coord):    
        path_to_grp = "/%s/%s/%s/%s/%s/%s/%s" % (CH5Const.PREFIX, CH5Const.PLATE, "%s", CH5Const.WELL, "%s", CH5Const.SITE, "%s")
        path_to_grp = path_to_grp % (coord.plate, coord.well, str(coord.site))
        pos_grp = self._f.require_group(path_to_grp)
        
        pos_grp.require_group(CH5Const.IMAGE)
        pos_grp.require_group(CH5Const.OBJECT)
        pos_grp.require_group(CH5Const.FEATURE)
        
        return CH5PositionWriter(coord, path_to_grp, self)
        
class CH5PositionWriter(cellh5.CH5Position):
    def __init__(self, coord, pos_grp, parent):
        super(CH5PositionWriter, self).__init__(coord.plate, coord.well, coord.site, pos_grp, parent)
        
    def add_image(self, data=None, shape=None, dtype=None, order=CH5Const.DEFAULT_IMAGE_ORDER):
        if data is not None:
            assert len(data.shape) == 5, "Image data must be 5-dimensional"
            self.get_group(CH5Const.IMAGE).create_dataset(CH5Const.RAW_IMAGE, data=data)
            return 
            
        elif shape is not None and dtype is not None:
            assert len(shape) == 5, "Image data must be 5-dimensional"
            img_dset = self.get_group(CH5Const.IMAGE).create_dataset(CH5Const.RAW_IMAGE, shape=shape, dtype=dtype)
            return CH5ImageWriter(img_dset, order, self)
        else:
            raise ValueError("Specify data, or shape and dtype") 
        
    def add_label_image(self, data=None, shape=None, dtype=None, order=CH5Const.DEFAULT_IMAGE_ORDER):
        if data is not None:
            assert len(data.shape) == 5, "Image data must be 5-dimensional"
            self.get_group(CH5Const.IMAGE).create_dataset(CH5Const.LABEL_IMAGE, data=data)
            return 
            
        elif shape is not None and dtype is not None:
            assert len(shape) == 5, "Image data must be 5-dimensional"
            img_dset = self.get_group(CH5Const.IMAGE).create_dataset(CH5Const.LABEL_IMAGE, shape=shape, dtype=dtype)
            return CH5ImageWriter(img_dset, order, self)
        else:
            raise ValueError("Specify data, or shape and dtype") 
        
    def add_region_object(self, name):
        # check if region name exists
        obj_grp = self.get_group(CH5Const.OBJECT)
        return CH5RegionWriter(name, obj_grp, self)
    
    def add_object_feature(self, object_name, feature_name, dtype=None):
        # check if region name exists
        feat_grp = self.get_group(CH5Const.FEATURE)
        obj_feat_grp = feat_grp.require_group(object_name)
        return CH5FeatureWriter(feature_name, object_name, obj_feat_grp, dtype, self)
        
        
        

class CH5PositionWriterBase(object):
    def __init__(self, parent_pos):
        self.parent_pos = parent_pos
        self.finished = False
        
    def finalize(self):
        self.finished = True
        
    def write(self, *args, **kwargs):
        raise NotImplementedError("Abstract method")
    
    def write_definition(self, *args, **kwargs):
        raise NotImplementedError("Abstract method")
            
class CH5ImageWriter(CH5PositionWriterBase):
    def __init__(self, dset, order, parent_pos):
        super(CH5ImageWriter, self).__init__(parent_pos)
        self.order = order
        self.dset = dset
        
    def insert_image(self, img, c, z, t):
        slices = []
        for d in self.order:
            if d == "c":
                slices.append(c)
            elif d == "t":
                slices.append(t)
            elif d == "z":
                slices.append(z)
            else:
                slices.append(slice(None))
                
        self.dset[tuple(slices)] = img
        log.debug("CH5ImageWriter: inserted image c=%d t=%d z=%d..." % (c,t,z))
        
    def write(self, *args, **kwargs):
        self.insert_image(*args, **kwargs)
        
    def write_definition(self, channel_description):        
        img_def_grp = self.parent_pos.definitions.get_definition_root().require_group(CH5Const.IMAGE)
        img_def_grp.create_dataset(os.path.split(self.dset.name)[1], data=channel_description.ro_recarray())
        
class CH5ObjectWriter(CH5PositionWriterBase):
    pass

class CH5RegionWriter(CH5ObjectWriter):
    dtype = numpy.dtype([('time_idx', 'int32'),('obj_label_id', 'int32'),])
    init_size = 500
    def __init__(self, name, obj_grp, parent_pos):
        super(CH5RegionWriter, self).__init__(parent_pos)
        self.name = name
        self.obj_grp = obj_grp
        self.dset = self.obj_grp.create_dataset(self.name, shape=(self.init_size,), dtype=self.dtype, maxshape=(None,))
        self.offset = 0 
        
    def write(self, t, object_labels):
        if len(object_labels) + self.offset > len(self.dset) :
            # resize
            self.dset.resize((len(object_labels) + self.offset,))
            
            
        object_labels = object_labels.astype(numpy.int32)
        times = numpy.repeat(t, len(object_labels))
        
        
            
        self.dset[self.offset:self.offset+len(object_labels)] = numpy.c_[times, object_labels].view(dtype=self.dtype).T
        
        self.offset+=len(object_labels)
        
    def write_definition(self):
        img_def_grp = self.parent_pos.definitions.get_definition_root().require_group(CH5Const.OBJECT)
        def_dset = img_def_grp.create_dataset(os.path.split(self.dset.name)[1], shape=(1,), dtype=numpy.dtype([('name', '|S512'), ('type', '|S512'), ('source1', '|S512'), ('source2', '|S512')]))
        def_dset[0] = [(self.name, 'region', '', '')]
        
    def finalize(self):
        self.dset.resize((self.offset,))
        super(CH5RegionWriter, self).finalize()    

class CH5FeatureWriter(CH5PositionWriterBase):
    init_size = 500
    def __init__(self, feature_name, object_name, obj_grp, dtype, parent_pos):
        super(CH5FeatureWriter, self).__init__(parent_pos)
        self.name = feature_name
        self.obj_grp = obj_grp
        self.dset = self.obj_grp.create_dataset(self.name, shape=(self.init_size,), dtype=dtype, maxshape=(None,))
        self.offset = 0 
        self.dtype = dtype
        self.object_name = object_name
        
    def write(self, data):
        if len(data) + self.offset > len(self.dset) :
            # resize
            self.dset.resize((len(data) + self.offset,))
            

        self.dset[self.offset:self.offset+len(data)] = data.view(dtype=self.dtype)[:,0]
        
        self.offset+=len(data)
        
    def write_definition(self):
        feat_grp = self.parent_pos.definitions.get_definition_root().require_group(CH5Const.FEATURE)
        feat_obj_grp = feat_grp.require_group(self.object_name) 
        def_dset = feat_obj_grp.create_dataset(os.path.split(self.dset.name)[1], shape=(len(self.dtype),), dtype=numpy.dtype([('name', '|S512')]))
        def_dset[:] = numpy.array(zip(*self.dtype.descr)[0])

class CH5Validator(cellh5.CH5File):
    pass


if __name__ == "__main__":
    filename = "test.ch5"
    raw = (numpy.random.rand(2,10,1, 200, 300) * 255).astype(numpy.uint8)
    seg = (numpy.random.rand(3,10,1, 200, 300) * 4065).astype(numpy.uint16)
    meta = {}
    
    cfw = CH5FileWriter(filename)
    
    cpw = cfw.add_position(CH5PositionCoordinate('my_plate', 'A01', 1))
    
    ciw = cpw.add_image(shape=raw.shape, dtype=raw.dtype)
    
    for c in range(2):
        for t in range(10):
            for z in range(1):
                ciw.write(raw[c,t,z,:,:], c=c, t=t, z=z)            
    ciw.finalize()
    
    c_def = CH5ImageChannelDefinition()
    c_def.add_row(channel_name='1', description='rfp', is_physical=True, voxel_size=(1,1,1), color="#aabbcc")
    c_def.add_row(channel_name='2', description='gfp', is_physical=True, voxel_size=(1,1,1), color="#aabbcc")

    ciw.write_definition(c_def)
    
    crw = cpw.add_label_image(shape=seg.shape, dtype=seg.dtype)
    for c in range(2):
        for t in range(10):
            for z in range(1):
                crw.write(raw[c,t,z,:,:], c=c, t=t, z=z)            
    ciw.finalize()
    
    r_def = CH5ImageRegionDefinition()
    r_def.add_row(region_name='seg c 1', channel_idx='0')
    r_def.add_row(region_name='seg c 2', channel_idx='1')
    r_def.add_row(region_name='seg c 2', channel_idx='1')
    
    crw.write_definition(r_def)
    
    object_labels = numpy.random.randint(0,256, 300)
    object_labels2 = numpy.random.randint(0,1256, 6000)
    
    cow = cpw.add_region_object('seg c 1')
    cow.write(t=0, object_labels=object_labels)
    cow.write(t=1, object_labels=object_labels)
    cow.write(t=2, object_labels=object_labels2)
    
    cow.write_definition()
    cow.finalize()
    
    cfew = cpw.add_object_feature(object_name='seg c 1', feature_name="bounding_box", dtype = numpy.dtype([('left', 'int32'),('right', 'int32'),('top', 'int32'),('bottom', 'int32'),]))
    
    bb = numpy.random.randint(0,256, 100).reshape((-1,4))
    
    cfew.write(bb)
    cfew.write_definition()
    
    
    cfw.close()
    print "the fin"
        
        