"""
Méthode définissant la structure de données receuillant les informations nécessaires
au fonctionnement du programme
"""
import pandas as pd
import numpy as np
import json
from uuid import uuid4
from dataclasses import dataclass,field
from typing import Optional

from PyQt6 import QtCore,QtGui
from PyQt6.QtWidgets import QTreeWidgetItem
import pyqtgraph as pg
from pyqtgraph.graphicsItems.ScatterPlotItem import name_list

from ressources import custom_items, custom_types,custom_struct_functions


CLASS_REGISTRY = {}
AXYS_TYPES = custom_types.axisScale._member_names_

def register_class(cls):

    CLASS_REGISTRY[cls.__name__] = cls

    return cls



class BaseObject:

    SERIALIZABLE_FIELDS = []
    PARAMETER_SCHEMA= {}

    def __init__(self, name:str):

        self.uuid = str(uuid4())
        self.name = name

        self.parent = None
        self._children = []

    @property
    def children(self):
        return self._children

    def add_child(self, child):

        child.parent = self
        self._children.append(child)

    def remove_child(self, child):

        child.parent = None
        self._children.remove(child)

    def serialize_attributes(self):

        return {
            field: getattr(self, field)
            for field in self.SERIALIZABLE_FIELDS
        }

    def to_dict(self):

        return {
            "type": self.__class__.__name__,
            "attributes": self.serialize_attributes(),
            "children": [
                child.to_dict()
                for child in self.children
            ]
        }


    @classmethod
    def from_dict(cls, data):

        object_type = data["type"]
        object_class = CLASS_REGISTRY[object_type]

        obj = object_class._from_attributes(
            data["attributes"]
        )

        obj._load_children(
            data["children"]
        )

        return obj


class ObjectLibrary(BaseObject):

    ACCEPTED_TYPES = ()

    def validate(self, obj):

        pass

    def add(self, obj):

        self.validate(obj)
        self.add_child(obj)



class ComponentLibrary(ObjectLibrary):

    ACCEPTED_TYPES = (ComponentObject,)
    PARAMETER_SCHEMA= {
                        'New component'    :{
                                            'type':'action',
                                            "key": "add_component"
                                        },
                        }

    def __init__(self):

        super().__init__("Components")

    def validate(self, obj):

        if not isinstance(obj, self.ACCEPTED_TYPES):

            raise TypeError("Only ComponentObject allowed" )

        if self.find_name(obj.name):
            raise ValueError(
                f"component {obj.name} already exists"
            )

    def find_name(self,name):
        pass


class ConverterLibrary(ObjectLibrary):

    ACCEPTED_TYPES = (ConverterObject,)
    PARAMETER_SCHEMA= {
                        'New converter'    :{
                                            'type':'action',
                                            "key": "add_converter"
                                        },
                        }
    def __init__(self):

        super().__init__("Converters")
        
    def validate(self, obj):

        if not isinstance(obj, self.ACCEPTED_TYPES):

            raise TypeError("Only ComponentObject allowed" )

class SimulationLibrary(ObjectLibrary):

    ACCEPTED_TYPES = (SimulationObject,)
    PARAMETER_SCHEMA= {
                        'New simulation'    :{
                                            'type':'action',
                                            "key": "add_simulation"
                                        },
                        }
    def __init__(self):

        super().__init__("Simulations")

    def validate(self, obj):

        if not isinstance(obj, self.ACCEPTED_TYPES):

            raise TypeError("Only ComponentObject allowed" )


class ConverterObject(BaseObject):
    pass


class SimulationObject(BaseObject):
    
    pass

class ComponentObject(BaseObject):
    """
    Représente un fichier chargé (CSV, CAN, UDP...), contenant :

    - un DataFrame complet
    - tous les SignalObject (raw + calculés)
    """


    item_type = custom_items.itemType.FILE
    PARAMETER_SCHEMA= {
                        'File name'    :{
                                            'type':'str',
                                            'default':None,
                                            "readonly": True,
                                            "key": "name"
                                        },
                        'File editor' :{
                                            'type': 'group',
                                            'expanded':True,
                                            'children':
                                                    {
                                                    'Time offset':{
                                                                        'type':'float',
                                                                        'default':0.0,
                                                                        'suffix': "s",
                                                                        "readonly": False,
                                                                        "key": "offset"
                                                                        },
                                                    'Truncate left':{
                                                                        'type':'float',
                                                                        'default':0.0,
                                                                        'limits':[0.0,None],
                                                                        "suffix": "s",
                                                                        "readonly": False,
                                                                        "key": "start_x"
                                                                        },
                                                    'Truncate right':{
                                                                        'type':'float',
                                                                        'default':0.0,
                                                                        'limits':[0.0,None],
                                                                        "suffix": "s",
                                                                        "readonly": False,
                                                                        "key": "stop_x"
                                                                        }
                                                    }
                                        }
                    }

    n_colors=20

    def __init__(self, fileData : FileStruct ):

        for key,val in fileData.__dict__.items():
            setattr(self,key,val)

        self.address        :   str
        self.sampling       :   float
        self.n_samples      :   int
        self.recordDate     :   str
        self.import_params  :   list[bool]
        self.data           :   pd.DataFrame
        self.name           :   str
        self.file_type      :   str
        self.start_x        :   float
        self.stop_x         :   float
        self.offset         :   int

        self.signals = []   # Liste de SignalObject
        self.is_selected = False
        self.opts_dict = custom_struct_functions.generate_opts_dict(self.PARAMETER_SCHEMA)
        self.colormap = pg.colormap.getFromMatplotlib('tab20')
        self.colors = self.colormap.getLookupTable(0,1,self.n_colors)
        #+ 4 styles de pinceaux, soit 4*n_colors combinaisons
        self.penStyle = [QtCore.Qt.PenStyle.SolidLine,
                        QtCore.Qt.PenStyle.DashLine,
                        QtCore.Qt.PenStyle.DotLine,
                        QtCore.Qt.PenStyle.DashDotLine]

    @property
    def signalsCount (self)-> int:
        return len(self.signals)

    def set_offset(self,time):
        if time is not None:
            if  time != self.offset:
                self.offset = time
                if isinstance(self.data.index, pd.MultiIndex):
                    #on retire l'index time existant
                    self.data = self.data.reset_index(level = 1,drop = True)
                #ajout d'une colonne Time / pas besoin de l'insérer en tête de la dataFrame
                #comme dans les versions précédentes
                self.data['Time'] = np.linspace(self.offset,
                                                self.offset+(self.n_samples-1)*self.sampling,
                                                self.n_samples)
                #on définit la nouvelle colonne time comme deuxième index
                self.data = self.data.set_index('Time',append = True)

    @property
    def display_name(self):
        """Le signal a-t-il subit une modification"""
        return self.name + (" *" if self.offset!=0 or self.start_x!=0 or self.stop_x!=0 else "")

    def get_params(self)-> dict:
        """Récupère l'ensemble des paramètres du signal sous forme de dictionnaire clé-valeur,
        à partir de la structure définie dans opts_dict."""

        return {key:getattr(self, key) for param_path,key in self.opts_dict.items()}

    def get_param(self,key):
        """Récupère la valeur d'un paramètre à partir de sa clé."""
        return getattr(self, key)

    def set_params(self,newParams):
        """Met à jour les paramètres du signal à partir d'un groupe de paramètres."""
        '''_params = custom_struct_functions.extract_parameter_values(   self.PARAMETER_SCHEMA,
                                                                    newParams)'''

        for key, value in newParams.items():
            if key == "offset":
                self.set_offset(value)
            else:
                setattr(self, key, value)

    def add_signal(self, name: str):
        """Ajoute un signal brut ou calculé."""
        pen=self.getDefaultPen()
        sig = SignalObject(self, name,pen)
        self.signals.append(sig)
        return sig

    def get_Y_from_X_index(self,index:int):
        """
        Méthode ne retourant que toutes les valeur en ordonnées des signaux passés par index.
        Args:
            index (int): index des channels devant être récupérés
        Returns:
            pandas.dataframe: données
        """

        if index>=self.n_samples:
            return None
        else:
            try:
                return self.data.iloc[index,:]
            except:
                print(f'{self.name} getYValues(): {index} / {self.n_samples}')

    def getDefaultPen(self,index:int=None):
        """ Méthode retournant le pinceau (couleur+type de trace) du signal en fonction de
            l'index qui lui ai passé

        Args:
            index (int): index de la courbe

        Returns:
            {pg.mkPen}: pen/pinceau de la courbe
        """
        if index is None:
            index = self.signalsCount

        if index >= self.n_colors:
            id_style = index // self.n_colors
            id_color = index % self.n_colors
        else:
            id_style = 0
            id_color = index
        return pg.mkPen(color=self.colors[id_color], style= self.penStyle[id_style])

    def to_dict(self):

        obj_params=self.get_file_loader_params()
        arg_to_export= ['signals']
        obj_params.update({k: v for k, v in self.__dict__.items() if k in arg_to_export })
        obj_params['signals'] = [sig.to_dict() for sig in obj_params['signals']]

        return obj_params
    
    def get_file_loader_params(self):
        
        arg_to_export= ['file_type','import_params','address']
        obj_params = {k: v for k, v in self.__dict__.items() if k in arg_to_export }
        
        return obj_params

    def resolve_filter_references(self):
            """
            Résout toutes les références différées (ex: DiffFilter)
            après que tous les SignalObject ont été recréés.
            """
            # les analyses diff_external font référence à des signaux qui n'appartiennent pas
            # au même fileOBject, c'est donc à la fin du chargement de tout le workspace
            # qu'on peut résoudre ces références
            signal_map = { sig.name: sig   for sig in self.signals }
            for sig in self.signals:
                for filt in sig.pipeline: #! orderedDict
                    if filt.action_type.name == "DIFF":
                        filt.resolve_reference(signal_map)


    def signals_from_dict(self,data, filter_factory,analyses_factory):

        for sig_data in data["signals"]:
            sig = SignalObject.from_dict(self, sig_data, filter_factory,analyses_factory)
            self.signals.append(sig)
        self.resolve_filter_references()

    def get_raw_y(self,name):
        """Vraies données brutes."""
        return np.array(self.data[name].values.tolist())

    def get_raw_x(self):
        """Vraies données brutes."""
        return np.array(self.data.index.get_level_values(1).values.tolist())


class CharacterizationObject(BaseObject):
    
    PARAMETER_SCHEMA = {
                            "Name": {},
                            "X Unit": {},
                            "Y Unit": {},
                        }
    def __init__(self,name,x_variable,sweep_variable):

        super().__init__(name)

        self.x_variable = x_variable
        self.sweep_variable = sweep_variable
        self.chart = None

class CharacteristicObject(BaseObject):

    PARAMETER_SCHEMA = {
                            "Name": {},
                            "X Unit": {},
                            "Y Unit": {},
                        }

    def __init__(self,
                name,
                characteristic_type):

        super().__init__(name)
        self.characteristic_type = characteristic_type
        self.chart = None



class CurveObject(BaseObject):
    """
    Représente un signal, dont les données sont calculées dynamiquement
    grâce à un pipeline de filtres non destructif.
    """
    item_type = custom_items.itemType.RAW
    PARAMETER_SCHEMA= {
                        'Curve name'    :{
                                            'type':'str',
                                            'default':None,
                                            "readonly": True,
                                            "key": "name"
                                        },
                        'Curve unit'    :{
                                            'type':'str',
                                            'default':"°C",
                                            "readonly": False,
                                            "key": "unit"
                                        },
                        'Curve Filters' :{
                                            'type': 'group',
                                            'expanded':True,
                                            'children':
                                                    {
                                                    'Filter curve':{
                                                                    'type':'action',
                                                                    "key": "filter_curve"
                                                                    },
                                                    'Cut-off frequency':{
                                                                        'type':'float',
                                                                        'limits':[0.00001,None],
                                                                        "readonly": False,
                                                                        "key": "cut_off_freq"
                                                                        },
                                                    }
                                        },
                        'Curve pen'     : {
                                            'type':'pen',
                                            'expanded':True,
                                            "readonly": False,
                                            "key": "pen"
                                            }
                    }

    def __init__(self,  file_obj: FileObject,  name: str, pen:pg.mkPen = None ):
        self.file = file_obj
        self.name = name
        # propriétés graphiques
        self.visible = True
        self.is_selected = False
        self.is_reference = False
        self.unit ='°C'
        self.pen = pen
        self.opts_dict = custom_struct_functions.generate_opts_dict(self.PARAMETER_SCHEMA)
        self.cut_off_freq=0.005
        self.filter_curve=False
        # pipeline de filtres : liste de FilterNode
        self.pipeline = OrderedDict()

        # liste des analyses
        self.analyses = OrderedDict()

        # liste des modèles/signaux dérivés
        self.derived_signals = []

        # cache interne
        self._cache = None
        self._cache_valid = False

    # ---------------- BASIC RAW ACCESS ----------------

    @property
    def x(self):
        """Axe des abscisses (colonne 0 du DataFrame)."""
        return self.file.get_raw_x()

    @property
    def is_modified(self):
        """Le signal a-t-il subit une modification"""
        return len(self.pipeline)>0 #! orderedDict

    @property
    def display_name(self):
        """Le signal a-t-il subit une modification"""
        return self.name + (" *" if self.is_modified else "")

    @property
    def raw_y(self):
        """Vraies données brutes."""
        return self.file.get_raw_y(self.name)

    # ---------------- PIPELINE COMPUTATION ----------------
    def compute(self):
        """Calcule y en appliquant chaque filtre dans l’ordre."""
        if self._cache_valid:
            return self._cache

        y = self.raw_y.copy()
        if self.pipeline:
            for node in self.pipeline: #! orderedDict
                y = node.apply(self.x, y)

        self._cache = y
        self._cache_valid = True
        return y

    @property
    def y(self):
        """Accès direct aux données calculées."""
        return np.array(self.compute())

    def invalidate(self):
        """À appeler lorsqu'un filtre est modifié, ajouté ou supprimé."""
        self._cache_valid = False

    def get_params(self):
        """Récupère l'ensemble des paramètres du signal sous forme de dictionnaire clé-valeur,
        à partir de la structure définie dans opts_dict."""

        return {key:getattr(self, key) for param_path,key in self.opts_dict.items()}

    def get_param(self,key):
        """Récupère la valeur d'un paramètre à partir de sa clé."""
        return getattr(self, key)

    def set_params(self,newParams):
        """Met à jour les paramètres du signal à partir d'un groupe de paramètres."""
        '''_params = custom_struct_functions.extract_parameter_values(   self.PARAMETER_SCHEMA,
                                                                    newParams)'''

        for key, value in newParams.items():
            print(f"Setting {key} to {value}")
            setattr(self, key, value)


    def get_filter_by_id(self, fid):
        return self.pipeline.get(fid)

    def get_analysis_by_id(self, aid):
        return self.analyses.get(aid)

    def get_filter_index(self, fid):
        return list(self.pipeline.keys()).index(fid)

    def get_analysis_index(self, aid):
        return list(self.analyses.keys()).index(aid)

    def get_filter_by_index(self, idx):
        return list(self.pipeline.values())[idx]

    def get_analysis_by_index(self, idx):
        return list(self.analyses.values())[idx]




class ChartObject(BaseObject):
    
    PARAMETER_SCHEMA = {
                            "Image Path": {
                                "type"      : "file",
                                "default"   : "",
                                "fileMode"  : "AnyFile",
                                "key"       : "path",
                                },
                            "X Scale": {
                                "type"      : "list",
                                "default"   : AXYS_TYPES[0],
                                "limits"    : AXYS_TYPES,
                                "key"       : "x_scale"
                                },
                            "Y Scale": {
                                "type"      : "list",
                                "default"   : AXYS_TYPES[0],
                                "limits"    : AXYS_TYPES,
                                "key"       : "y_scale"
                                }
                            }

    SERIALIZABLE_FIELDS = [
                                "path",
                                "rotation"
                            ]

    def __init__(self):

        super().__init__("Chart")
        self.opts_dict = custom_struct_functions.generate_opts_dict(self.PARAMETER_SCHEMA)
        self.x_axis = custom_items.AxisCalibration()
        self.y_axis = custom_items.AxisCalibration()
        

    @property
    def path(self):
        return self.get_param('path')

    def get_params(self):
        """Récupère l'ensemble des paramètres du signal sous forme de dictionnaire clé-valeur,
        à partir de la structure définie dans opts_dict."""

        return {key:getattr(self, key) for param_path,key in self.opts_dict.items()}

    def get_param(self,key):
        """Récupère la valeur d'un paramètre à partir de sa clé."""
        return getattr(self, key)

@register_class
class Workspace(BaseObject):

    def __init__(self):

        self.children = [
                        ComponentLibrary(),
                        ConverterLibrary(),
                        SimulationLibrary()
                        ]

    def children(self):

        return self.components

    def add_component(self, component):
        #todo: gérer l'affectation selon la classe de l'objet children qui lui est passé
        self.components.append(component)

    @classmethod
    def _from_attributes(cls, attributes):

        return cls()

    def _load_children(self, children):
        #todo: gérer l'affectation selon la classe de l'objet children qui lui est passé
        self.components = [
                            self.from_dict(child)
                            for child in children
                        ]


class WorkspaceSerializer:

    def save(workspace,path):
        with open(path, "w", encoding="utf-8") as f:
            export=workspace.to_dict()
            json.dump(export, f, indent=2)
    '''
    @staticmethod
    def load(path, filter_factory):

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        ws = Workspace()
        file_names=[]
        for file_data in data["workspace"]["files"]:

            file_obj = FileObject.from_dict(file_data, filter_factory)
            ws.add_file(file_obj)
            file_names.append(file_obj.name)

        # Après avoir créé tous les FileObject et SignalObject,
        # on peut résoudre les références différées (ex: diff_external)
        for file_obj in ws.files:
            for sig in file_obj.signals:
                for analysis in sig.analyses:
                    #! analysis.id = data["id"] <= il faut recharger l'id sauvegardé
                    if analysis.action_type.name == "DIFF_EXT":
                        ref_file =  [   file for file in ws.files if
                                        file.name == analysis.params['reference_file']][0]
                        analysis.resolve_reference({s.name: s for s in ref_file.signals})
        return ws
        '''



@dataclass(frozen=True)
class SelectionContext:
    role:               custom_items.itemType
    signal:             SignalObject
    filter_id:          Optional[str] = None
    analysis_id:        Optional[str] = None

    
    def get_filter(self):
        return self.signal.get_filter_by_id(self.filter_id)

    def get_analysis(self):
        return self.signal.get_analysis_by_id(self.analysis_id)

    
'''
class Parameter():

    def __init__(self,struct:custom_items.ParameterStruct=None):

        self.struct=struct
        self.curves:list[DigitizedCurve]=[]
        if self.struct.coordinate is not None :
            self.updateScale()
        self.n_colors=6
        if struct.adress is not None:
            img=QtGui.QImage(QtGui.QPixmap(struct.adress))
            img=pg.imageToArray(img, copy=True,transpose=False)
            np_array=np.rot90(np.flip(img,(1,0)))
            imgitem = pg.ImageItem(np_array)
            self.shape=imgitem.image.shape
        #colormap découpée en n_colors
        self.colormap = pg.colormap.get('tab20')
        self.colors = self.colormap.getLookupTable(0,1,self.n_colors)
        #+ 4 styles de pinceaux, soit 4*n_colors combinaisons
        self.penStyle = [QtCore.Qt.PenStyle.SolidLine,
                        QtCore.Qt.PenStyle.DashLine,
                        QtCore.Qt.PenStyle.DotLine,
                        QtCore.Qt.PenStyle.DashDotLine]

    @property
    def n_curves(self):
        res = len(self.curves)-1
        return res if res > 0 else 0

    @property
    def delta(self):

        return self._delta

    @property
    def offset_scale(self):
        return self._offset_scale

    def addCurve(self,struct:custom_items.CurveStruct,data=None):
        struct.file_id=[self.struct.file_id[0],self.struct.file_id[1],len(self.curve)]
        self.curves.append(DigitizedCurve(struct))


    def removeParameter(self,id):
        del(self.parameters[id])

    def toXML(self):
        pass

    def updateScale(self):
        #Xaxis log?
        scale=self.struct.coordinate
        if scale.xlog==True:
            offset_dx=np.log10(scale.xmin)
            dx=np.log10(scale.xmax/scale.xmin)
        else:
            offset_dx=scale.xmin
            dx=scale.xmax-scale.xmin
        #Ylog?
        if scale.ylog==True:
            offset_dy=np.log10(scale.ymin)
            dy=np.log10(scale.ymax/scale.ymin)
        else:
            offset_dy=scale.ymin
            dy=scale.ymax-scale.ymin
        self._offset_scale=(offset_dx,offset_dy)
        self._delta=(dx,dy)



    """ Actuellement le graph recharge l'image depuis l'adresse de l'item choisi
    def setGraph(self,IMG):
        self.graph=IMG
    def getGraph(self):
        return self.graph
        """

    def getTreeItem(self):
        item=custom_items.parameterTreeItem(struct=self.struct)

        if self.curves:
            for curve in self.curves:
                child=curve.getTreeItem()
                item.addChild(child)
        return item

    def getDefaultPen(self,index):
        """Méthode retournant le pinceau (couleur + type de trace) par défaut du signal
        Args:
            index {int}       -- index de la courbe
        Returns:
            {pyqtGraph.mkPen} -- pinceau de type pg.mkPen
        """

        if index >= self.n_colors:
            id_style = index//self.n_colors
            id_color = index%self.n_colors
        else:
            id_style = 0
            id_color = index
        return pg.mkPen(color=self.colors[id_color],style=self.penStyle[id_style])

    def getDefaultCurve(self,index)->custom_items.CurvePenStruct:
        """Méthode retournant l'intégralité de la structure définissant l'apparance
        d'un scatterPlot

        Args:
            index {int}       -- index de la courbe
        Returns:
            {custom_items.CurvePenStruct} -- structure gérant l'aspect de scatterplot
        """
        if index >= self.n_colors:
            id_style = index//self.n_colors
            id_color = index%self.n_colors
        else:
            id_style = 0
            id_color = index
        defaulCurve=custom_items.CurvePenStruct(pen=pg.mkPen(color=self.colors[id_color],
                                                        style=self.penStyle[id_style]),
                                                symbol_color=pg.mkColor(self.colors[id_color]),
                                                symbol=name_list[id_style],
                                                symbol_size=5
                                                )
        return defaulCurve

    def getChildData(self,id):
        return self.curves[id]

class Component():

    def __init__(self,struct:custom_items.componentStruct=None):
        self.struct=struct
        self.parameters:list[Parameter]=[]

    def removeParameter(self,id):
        del(self.parameters[id])

    def toXML(self):
        pass

    def getTreeItem(self):

        item=custom_items.componentTreeItem(struct=self.struct)
        if self.parameters:
            for parameter in self.parameters:
                child=parameter.getTreeItem()
                item.addChild(child)
        return item

    def addParameter(self,parameter:Parameter):
        self.parameters.append(parameter)

    def getChildData(self,id):
        return self.parameters[id]

class Model(QtCore.QObject):

    MAJ_curves=QtCore.pyqtSignal(QTreeWidgetItem)
    MAJ_files=QtCore.pyqtSignal()
    MAJ_component=QtCore.pyqtSignal(custom_items.MetaTreeItem)
    MAJ_options=QtCore.pyqtSignal()

    def __init__(self,components=None,session_settings=None):

        super(Model,self).__init__()
        #Liste de fichier Graphtec (et autres), constitué destructure de données décrite
        #dans CsvFiles
        self.components : list[Component] = components if components else []
        self._update_funcs = []
        #affection treefile au type QTreeWidget afin de bénificier de l'autocomplétion
        self.cpt_id = 0
        self.qitems_dict={}
        self.settings = {} if session_settings is not None else session_settings

    def getItemData(self,id_file=None,absolute_id=None):
        """
        Méthode facilitant l'accés au données des fichiers CSV
        Args:
            id_file (int): id du fichier GL
            attribute (str): str de l'attribut à récupérer
            kwargs () : données supplémentaires pouvant être nécessaire à certains attributs
        Returns:
            _type_: _description_
        """
        if id_file is None:
            id_file=self.qitems_dict[absolute_id].file_id
            print(f'ID: {id_file}')

        def recursiveGetter(item,index):
            print(index)
            if len(index)>1:
                id=index.pop(0)
                return recursiveGetter(item.getChildData(id),index)
            else:
                return item.getChildData(index[0])

        return recursiveGetter(self,id_file)



    def sortTableQitems(self,tab)->list:
        """
        Méthode interne renvoyant une liste des items sélectionnés groupés en listes
        en fonction de leur fichier d'origine
        Arguments:
            tab (list(QTreeWidgetItems)): items sélectionnés
        Returns:
            list:   structure contenant les listes des ids des signaux et de leur
                    nom groupés par fichier d'origine
        """
        sorted_id=sorted([(item.file_id,item) for item in tab],
                            key = lambda x: x[0][0])
        tab = [[] for _ in range(len(self.components))]
        [tab[val[0][0]].append(val[1]) for val in sorted_id]
        return [id_list for id_list in tab if id_list]

    def newComponent(self,component_type=custom_types.componentType.CUSTOM,**kwargs):
        """
        Création de l'arborescence à l'ouverture du programme : Component0 => Parameter0
        Dans cette configuration, le programme est près à réceptionner un graph/csv/xml
        Args:
            file (CsvFile): _description_
        """
        struct = custom_items.componentStruct(   name=f'Component{self.cpt_id}',
                                                    absolute_id=self.cpt_id,
                                                    file_id=[self.cpt_id],
                                                    manufacturer='Custom')

        new_component=Component(struct=struct)
        self.appendItemsDict(new_component.getTreeItem())
        path=kwargs.get('IMG',None)

        if component_type is custom_types.componentType.CUSTOM:
            struct = custom_items.ParameterStruct(   name=f'Parameter0',
                                                    absolute_id=self.cpt_id,
                                                    file_id=[0,0],
                                                    adress=path,
                                                    coordinate=custom_items.CoordinateStruct())
            new_param=Parameter(struct)
            new_component.addParameter(new_param)
            self.appendItemsDict(new_param.getTreeItem(),new_component.getTreeItem())
        else:
            struct_dict={
                            custom_types.componentType.MOSFET:custom_items.MOSFETStruct,
                            custom_types.componentType.DIODE:custom_items.DiodeStruct
                        }
            data=struct_dict[component_type]()
            for n,var in enumerate(vars(data)):
                struct = custom_items.ParameterStruct(   name=f'{var}',
                                                        absolute_id=self.cpt_id,
                                                        file_id=[0,n],
                                                        adress=None,
                                                        coordinate=custom_items.CoordinateStruct())
                new_param=Parameter(struct)
                new_component.addParameter(new_param)
                self.appendItemsDict(new_param.getTreeItem(),new_component.getTreeItem())

        self.components.append(new_component)
        self.MAJ_component.emit(new_component.getTreeItem())

    def addParameter(self,item:custom_items.parameterTreeItem,
                        param:custom_items.ParameterStruct=None,
                        cpt:int=None,
                        emit_MAJ=True):

        id_c=item.file_id[0]
        component=self.components[id_c]
        n_params=len(component.parameters)
        if param is None:
            param=custom_items.ParameterStruct(  name=f'Parameter{n_params}',
                                                file_id=0,
                                                absolute_id=cpt,
                                                adress=None,
                                                coordinate=custom_items.CoordinateStruct()
                                                )
        param.file_id=item.file_id.append(n_params)
        component.addParameter(Parameter(param))
        #! Ajouter un Item au dictionnaire ItemDict
        if emit_MAJ:
            self.MAJ_component.emit(item)

    def addCurve(self,item:custom_items.parameterTreeItem,
                    curve:custom_items.CurveStruct=None,
                    cpt:int=None,
                    emit_MAJ=True):

        id_c,id_p=item.file_id
        print(item.file_id)
        param:Parameter=self.components[id_c].parameters[id_p]
        n_curves=len(param.curves)
        if curve is None:
            curveAspect=param.getDefaultCurve(n_curves)
            curve=custom_items.CurveStruct(  name=f'Curve{n_curves}',
                                            file_id=[id_c,id_p,n_curves+1],
                                            absolute_id=cpt,
                                            pen=curveAspect.pen,
                                            symbol_color=curveAspect.symbol_color,
                                            symbol_size=curveAspect.symbol_size,
                                            symbol=curveAspect.symbol
                                        )
        curve.file_id=item.file_id.append(n_curves)
        param.addCurve(curve)
        #! Ajouter un Item au dictionnaire ItemDict
        if emit_MAJ:
            self.MAJ_component.emit(item)

    def appendItemsDict(self,item,parent=None):
        """_summary_
        Args:
            file (CsvFile): _description_
        """
        if parent is not None:
            item.parentId=parent.absoluteId
        #! appendItemsDict n'est actuellement appélée que par newComponent
        self.qitems_dict[self.cpt_id]=item
        self.cpt_id+=1

    def changeSettings(self,settings):
        self.settings = settings
        self.MAJ_options.emit()

    def getChildData(self,id):
        return self.components[id]

    
def main():

    df = pd.DataFrame()
    df["col1"] = [4,5,6,9,8,2,4,5]
    df["col2"] = [1,3,5,7,9,11,13,15]
    df['Time'] = np.linspace(0,7*0.124,8)
    df = df.set_index('Time',append=True)

if __name__ == '__main__':
    main()'''