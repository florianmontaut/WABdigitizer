from PyQt6.QtWidgets import  QTreeWidgetItem
from PyQt6 import QtGui,QtCore

from dataclasses import dataclass,field

import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
from pyqtgraph.graphicsItems.ScatterPlotItem import name_list
from .custom_parameters import ComplementaryElements,CurveModelizer,CurveModelItem
from .custom_types import itemType,qSignalType,componentType,axisScale



@dataclass
class AxisCalibration:

    pixel_start     : tuple[int,int]
    pixel_end       : tuple[int,int]
    value_start     : float
    value_end       : float
    scale           : axisScale



#?#####     old         #####?#
@dataclass
class CoordinateStruct():

    xmin : float =  field(default=0)
    xmax : float = field(default=1)
    ymin : float = field(default=0)
    ymax : float = field(default=1)
    xlog : bool = field(default=False)
    ylog : bool = field(default=False)
    xtick : int = field(init=False,default=5)
    ytick : int = field(init=False,default=5)
    xlabel : str = field(init=False,default="voltage")
    ylabel : str = field(init=False,default="current")



@dataclass
class MOSFETStruct():

    Eon         :   dict =  field(default_factory=lambda:  {'25':(0,0)})
    Eoff        :   dict =  field(default_factory=lambda:  {'25':(0,0)})
    Conduction  :   dict =  field(default_factory=lambda:  {'25':(0,0)})
    ThermalR    :   dict =  field(default_factory=lambda:  {'0':(1,1)})
    '''
    Coss        :   dict =  field(default=0.000001)
    Boitier     :   dict =  field(default='TO247')
    '''


@dataclass
class DiodeStruct():

    Err         :   dict =  field(default_factory=lambda:  {'25':(0,0)})
    conduction  :   dict =  field(default_factory=lambda:  {'25':(0,0)})
    ThermalR    :   dict =  field(default_factory=lambda:  {'0':(1,1)})


@dataclass
class StandardStruct():

    name         :   str
    item_type    :   itemType = field(init=False)
    file_id      :   int
    absolute_id  :   int

@dataclass
class componentStruct(StandardStruct):

    name            :   str
    #model adress of the component (not mandatory : does not exist at creation)
    adress          :   str = field(init=False)
    manufacturer    :   str

    def __post_init__(self):
        self.item_type=itemType.COMPONENT


@dataclass
class ParameterStruct(StandardStruct):

    #adress of the parameter graph (not mandatory : a parameter can be a table without graph)
    adress          :   str
    #coordinate of the graph (not mandatory : a parameter can be a table without graph)
    coordinate      :   CoordinateStruct

    def __post_init__(self):
        self.item_type=itemType.PARAM

@dataclass
class CurvePenStruct():

    pen             :   QtGui.QPen
    symbol_color    :   QtGui.QBrush
    symbol          :   str
    symbol_size     :   int

@dataclass
class CurveStruct(StandardStruct,CurvePenStruct):

    adress          :   str = field(init=False)

    def __post_init__(self):
        self.item_type=itemType.CURVE
        self.color=self.pen.color()


class MetaTreeItem(QTreeWidgetItem):
    """
    Classe générique héritant de QTreeWidgetItem.
    """
    def __init__(self,struct : StandardStruct  | componentStruct | ParameterStruct | CurveStruct,
                *args,**kwargs):
        self._parentId=None
        self.struct=struct
        QTreeWidgetItem.__init__(self)
        self.setFlags(self.flags())
        self.setText(0, self.struct.name)
        #self.setCheckState(0,QtCore.Qt.CheckState.Unchecked)

    #*Propriétés*#
    @property
    def absoluteId(self):
        """
        Reçoit (si un argument est passé) ou retourne l'index absolu du TreeWidgetItem.
        Cet index est donné par la méthode gérant l'affichage dans le treewidget parent.
        Returns:
            _absoluteIndex {int} : index
        """
        return self.struct.absolute_id

    @absoluteId.setter
    def absoluteId(self,index):
        self.struct.absolute_id=index

    @property
    def type(self)->itemType:
        """
        Retourne le itemType TreeWidgetItem :
        Returns:
            {itemType} : type de l'objet, RAW signal brut, FILE fichier, MODIF signal obtenue par
                        en modifiant un signal brut et MODEL un signal d'un modèle mathématique
        """
        return self.struct.item_type

    @type.setter
    def type(self,Itype:itemType)->None:
        self.struct.item_type=Itype

    @property
    def parentId(self):
        return self._parentId

    @parentId.setter
    def parentId(self,id:int):
        self._parentId=id

    @property
    def file_id(self):
        return self.struct.file_id

    @file_id.setter
    def file_id(self,id:list[int]):
        self.struct.file_id=id

    @property
    def name(self):
        return self.struct.name

    @name.setter
    def name(self,name:str):
        self.struct.name=name
        self.setText(0, self.struct.name)

    #*Méthodes*#
    def setItemFont(self,bold:bool=False,brush:pg.mkBrush=None):
        """
        Méthode permettant de modifier les données graphiques d'un TreeWidgetItem
        Arguments:
                bold    {bool,optional}  -- Le texte est-il en gras
                                            Defaults to None
                brush   {pg.mkBrush}     -- Objet pyqtgraph.mkPen définissant
                                            l'aspect de la courbe
        Returns:
        """

        font=QtGui.QFont()
        font.setBold(bold)
        self.setData(0,6,font)

        if brush is not None:
            self.setData(0,8,brush)
            self.setData(1,8,brush)
            self.brush=brush

    def addCurve(self):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        pass

    def getStructure(self):
        return self.struct

    def toggleCurve(self):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        pass

    def saveParam(self):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        self.name=self.item_params.child('Curve name').value()

    def addItem(self,item):
        """
        Super Méthode surchargée par toute classe héritant de l'objet CustomTreeItem
        """
        item.parentId(self.absoluteId)
        self.addChild(item)

class componentTreeItem(MetaTreeItem):
    """
    TreeItem incorporant les interfaces et méthodes permettant de gérer l'affichage d'un composant
    Args:
        CustomTreeItem (_type_): _description_
    """
    def __init__(self,struct:  componentStruct, *args,**kwargs):

        MetaTreeItem.__init__(self,struct,*args,**kwargs)
        self.ItemType(3)#Item type différent d'un QTreeWidgetItem standard

    def ItemParameters(self):

        children = [
                        {'name':'Component reference','type':'str',"value":self.name},
                        {'name':'Component type','type':'list','values':componentType,'value':componentType.CUSTOM},
                        {'name':'Manufacturer','type':'str',"value":self.struct.manufacturer},
                        {'name':'Add parameter', 'type': 'action'}
                    ]
        self.item_params=ptree.Parameter.create(name = 'Component infos', type = 'group',
                                        children = children)
        self.item_params.sigTreeStateChanged.connect(self.saveParam)
        return self.item_params

    def saveParam(self):
        self.name=self.item_params.child('Component reference').value()



class parameterTreeItem(MetaTreeItem):
    """
    TreeItem incorporant les interfaces et méthodes permettant de gérer l'affichage d'un composant
    Args:
        CustomTreeItem (_type_): _description_
    """
    def __init__(self,struct:  ParameterStruct, *args,**kwargs):

        MetaTreeItem.__init__(self,struct,*args,**kwargs)
        self.ItemType(3)#Item type différent d'un QTreeWidgetItem standard


    def ItemParameters(self):

        children = [{'name':'Parameter','type':'str','value': self.name},
                    {'name':'Graph adress','type':'file','value': self.struct.adress},
                    {'name':'Add curve', 'type': 'action'},
                    {'name':'Graph setup', 'type': 'group', 'children':
                    [
                        {'name': 'New axis', 'type': 'action'},
                        {'name': 'Set axis', 'type': 'action', 'children':
                        [
                            {'name': 'xmin', 'type': 'float',
                                'value': self.struct.coordinate.xmin},
                            {'name': 'xmax', 'type': 'float',
                                'value': self.struct.coordinate.xmax},
                            {'name': 'ymin', 'type': 'float',
                                'value': self.struct.coordinate.ymin},
                            {'name': 'ymax', 'type': 'float',
                                'value': self.struct.coordinate.ymax},
                            {'name': 'log X scale','type':'bool',
                                'value':self.struct.coordinate.xlog},
                            {'name': 'log Y scale','type':'bool',
                                'value':self.struct.coordinate.ylog},
                        ]},
                        {'name': 'Axis options', 'type': 'group', 'children':
                        [
                            {'name': 'X axis label', 'type': 'str',
                                    'value': self.struct.coordinate.xlabel},
                            {'name': 'X Tick number', 'type': 'int', 'limit':[1,None],
                                    'value': self.struct.coordinate.xtick},
                            {'name': 'Y axis label', 'type': 'str',
                                    'value': self.struct.coordinate.ylabel},
                            {'name': 'Y Tick number', 'type': 'int', 'limit':[1,None],
                                    'value': self.struct.coordinate.ytick}
                        ]},
                    ]}
                    ]
        self.item_params=ptree.Parameter.create(name = 'Parameters infos', type = 'group',
                                        children = children)
        self.item_params.sigTreeStateChanged.connect(self.saveParam)
        """
        self.item_params=ptree.Parameter.create(name='Functions', type='group', children=children)
        self.selectionTree.setParameters(self.item_params)
        self.item_params.param('Graph setup', 'New axis').sigActivated.connect(self.newGraphGrid)
        self.item_params.param('Graph setup', 'Set axis').sigActivated.connect(self.setGraphGrid)
        self.item_params.param('Curves functions', 'Add curve').sigActivated.connect(self.addCurve)
        self.set_Param_opts(self.item_params,table=[('Graph setup'),('Curves functions')],visible=False,
                                enabled=False)
        self.ExportB.clicked.connect(lambda: print(self.Get_Params_index(self.item_params)))
        self.plotgraph.scene().sigMouseClicked.connect(self.mouse_clicked)
        self.params_indexes=dict()
        """
        return self.item_params

    def saveParam(self):

        self.struct.adress=self.item_params.child('Graph adress').value()
        self.struct.coordinate.xmin=self.item_params.child( 'Graph setup',
                                                            'Set axis',
                                                            'xmin').value()
        self.struct.coordinate.xmax=self.item_params.child( 'Graph setup',
                                                            'Set axis',
                                                            'xmax').value()
        self.struct.coordinate.xlog=self.item_params.child( 'Graph setup',
                                                            'Set axis',
                                                            'log X scale').value()
        self.struct.coordinate.xlabel=self.item_params.child(   'Graph setup',
                                                                'Axis options',
                                                                'X axis label').value()
        self.struct.coordinate.xtick=self.item_params.child(    'Graph setup',
                                                                'Axis options',
                                                                'X Tick number').value()
        self.struct.coordinate.ymin=self.item_params.child( 'Graph setup',
                                                            'Set axis',
                                                            'ymin').value()
        self.struct.coordinate.ymax=self.item_params.child( 'Graph setup',
                                                            'Set axis',
                                                            'ymax').value()
        self.struct.coordinate.ylog=self.item_params.child( 'Graph setup',
                                                            'Set axis',
                                                            'log Y scale').value()
        self.struct.coordinate.ylabel=self.item_params.child(   'Graph setup',
                                                                'Axis options',
                                                                'Y axis label').value()
        self.struct.coordinate.ytick=self.item_params.child(    'Graph setup',
                                                                'Axis options',
                                                                'Y Tick number').value()

class curveTreeItem(MetaTreeItem):
    """
    TreeItem incorporant les interfaces et méthodes permettant de gérer l'affichage d'une courbe
    Args:
        CustomTreeItem (_type_): _description_
    """
    def __init__(self,struct: CurveStruct,
                    data,*args,**kwargs):

        MetaTreeItem.__init__(self,struct,*args,**kwargs)
        self.ItemType(2)#Item type différent d'un QTreeWidgetItem standard
        self.signal_data=data
        self.curve=None

        if self.struct.color:
            self.setItemFont(False,brush=pg.mkBrush(color=self.struct.color))

    def ItemParameters(self):

        children = [{'name':'Curve name','type':'str',"value":self.name},
                    {   'name':'Curve color','type':'pen',
                        'value':self.struct.pen,'expanded':False},
                    {'name':'Symbol parameters','type':'group','expanded':False,'children':
                        [
                        {'name':'Symbol shape','type':"list", 'values':name_list,
                            'value':self.struct.symbol},
                        {'name':'Symbol color','type':'color',
                            'value':self.struct.brush},
                        {'name':'Symbol size','type':"int",
                            'limits':[1,100],'value':self.struct.symbol_size},
                        ]},
                    CurveModelizer(name = 'Curve modeling', type = 'group',curveType = 'Thermal')
                    ]
        self.item_params=ptree.Parameter.create(name = 'Curve infos', type = 'group',
                                        children = children)

        self.item_params.sigTreeStateChanged.connect(self.saveParam)
        return self.item_params

    def generateCurve(self)->pg.PlotDataItem:
        """
        Méthode gérant la création et le paramétrage de l'objet graphique PlotDataItem curve
        """
        if not self.isDisabled():
            self.curve=pg.PlotDataItem(self.signal_data,pen = self.struct.pen)
            self.curve.setCurveClickable(True)
            self.curve.sigClicked.connect(lambda : self.emitItemID(qSignalType.SELECT))
            return self.curve
        else:
            return None

    def saveParam(self):

        self.name=self.item_params.child('Curve name').value()
        self.struct.pen=self.item_params.child('Curve color').value()
        self.struct.symbol=self.item_params.child('Symbol parameters','Symbol shape').value()
        self.struct.brush=self.item_params.child('Symbol parameters','Symbol color').value()
        self.struct.symbol_size=self.item_params.child('Symbol parameters','Symbol size').value()

        if self.curve is not None:
            self.curve.setPen(self.struct.pen)


