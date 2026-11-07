"""
Module contenant des QWidgets et QMainWindow générique pouvant être chargés pour différents projet
"""

import numpy as np

from PyQt6.QtWidgets import (QApplication, QMainWindow,QAbstractItemView,QGraphicsRectItem,QColorDialog,
                            QGraphicsItem,QWidget,QFileDialog,QTreeWidget,
                            QMessageBox,QGridLayout,QDialogButtonBox,QSizePolicy)

from PyQt6.uic import loadUi
from PyQt6 import QtGui,QtCore


from views import WabDialogs
from ressources import custom_functions,custom_types,custom_items

import pyqtgraph.parametertree as ptree
import pyqtgraph as pg

import pathlib,os

PATH=pathlib.Path(__file__).parent


class WabWindow(QMainWindow):
    """
    Fenêtre principale du GLviewer

    Class:
        QMainWindow (QMainWindow): _description_
    """
    #Les signaux ne peuvent être déclarés qu'en attributs de classe
    loadFile_signal=QtCore.pyqtSignal(tuple)
    modifCurve_signal=QtCore.pyqtSignal()
    UIsignals=QtCore.pyqtSignal(tuple)

    def __init__(self,params,**opts):

        super(WabWindow, self).__init__()
        #Load the UI Page
        loadUi(PATH/'WABDigitizer_V0.ui', self)
        self.setWindowIcon(QtGui.QIcon(str(PATH)+'/icon.ico'))
        self.componentTree:QTreeWidget
        self.windows_set = None
        self.graph_area = None
        self.default_dir=os.path.dirname(__file__)
        #lastest_dir sera mis à jour 
        self.latest_dir=os.path.dirname(__file__)
        
        
        
        
        '''
        ###old GL
        self.old_highlight=(None,None)
        ###old GL
        self.imgitem=None
        self.axis_configured=False
        self.curves=list()
        self.setAcceptDrops(True)

        self.optsDict = {   "X axis title"                          : "X_title",
                            "X axis unit"                           : "X_unit" ,
                            "Y axis title"                          : "Y_title",
                            "Y axis unit"                           : "Y_unit" ,
                            "Update axis when signal selected"      : "update_selected",
                            ("Downsample", "Active")                 : "downsample",
                            ("Downsample", "Downsampling factor")    : "downsample_ratio",
                            ("Downsample", "Downsampling type")      : "downsample_type",
                            }

        #options de l'objet
        self.opts=  {
                    "X_title"              : "Temps",
                    "X_unit"               : "s",
                    "Y_title"              : "Temperature",
                    "Y_unit"               : "°C",
                    "update_selected"      : True,
                    "downsample"           : True,
                    "downsample_ratio"     : 10,
                    "downsample_type"      : "peak",
                    }
        if opts:
            self.updateOptions(**opts)

        #*Réglage de l'affichage principal*#
        self.initView()
        #self.initGraphTree()
        self.actionQuit.triggered.connect(self.close)
        #*Réglage de l'arborescence*#
        #cache la colonne id
        self.componentTree.hideColumn(2)
        #options_params contient les paramètres à afficher lorsque l'utilisateur ouvre la fenêtre
        #des options
        self.option_params=params
        self.toggle_check=True
        self.graphWindows=[]
        self.selected_curve=[None,None]
        #dictionnaire reliant les clés des options de cet objet et le dictionnaire extrait de
        #la fenêtre options'''

    def initView(self):
        """
        Méthode gérant l'initialisation du graphique mainGraph,
        on ajoute un plot en position 0,0: plotgraph
        """
        self.plotgraph = self.mainGraph.addPlot(row = 0, col = 0)
        self.mainGraph.setBackground('lightgray')#passage du mainGraph en fond blanc
        #configuration de la sélection en mode single
        self.componentTree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        #cache la colonne id
        self.componentTree.hideColumn(2)
        self.componentTree.customContextMenuRequested.connect(self.treeMenu)

        #Ajout des actions du menu principal
        self.actiongraph.triggered.connect(lambda: self.loadFileDialog(fileType=custom_types.fileType.IMG))
        self.actionmodel.triggered.connect(self.loadFileDialog)
        self.actionQuit.triggered.connect(self.close)
        self.componentTree.itemClicked.connect(self.onItemClicked)

        #ajout du TableWidget "à la main" car la fonction load.ui n'arrive pas à créer cet objet
        # (loadUI passe un objet parent à TableWidget, qui n'en attend pas )
        self.tableXY=pg.TableWidget(editable=True,sortable=False)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(1)
        sizePolicy.setHeightForWidth(self.tableXY.sizePolicy().hasHeightForWidth())
        self.tableXY.setSizePolicy(sizePolicy)
        self.splitter_3.setOrientation(QtCore.Qt.Orientation.Vertical)
        self.splitter_3.addWidget(self.tableXY)

    def initSelectionTree(self):
        """
        Méthode gérant l'initialisation du Widget GraphTree
        """

        children = [{'name': 'Graph setup', 'type': 'group', 'children':
                    [
                        {'name': 'New axis', 'type': 'action'},
                        {'name': 'Set axis', 'type': 'action', 'children':
                        [
                            {'name': 'xmin', 'type': 'float', 'value': 0},
                            {'name': 'xmax', 'type': 'float', 'value': 1.0},
                            {'name': 'ymin', 'type': 'float', 'value': 0},
                            {'name': 'ymax', 'type': 'float', 'value': 1.0},
                            {'name': 'log X scale','type':'bool','value':False},
                            {'name': 'log Y scale','type':'bool','value':False},
                        ]},
                        {'name': 'Axis options', 'type': 'group', 'children':
                        [
                            {'name': 'X axis label', 'type': 'str', 'value':'Tension (V)'},
                            {'name': 'X Tick number', 'type': 'int', 'value': 10,'limit':[1,None]},
                            {'name': 'Y axis label', 'type': 'str', 'value':'Courant (A)'},
                            {'name': 'Y Tick number', 'type': 'int', 'value': 10,'limit':[1,None]}
                        ]}
                    ]},
                {'name': 'Curves functions', 'type': 'group', 'children':
                    [
                            {'name': 'Add curve', 'type': 'action','children':
                            [
                                {'name': 'use same X values', 'type': 'bool', 'value': True},
                                {'name':'curve name', 'type': 'str', 'value': 'curve'}
                            ]},
                    ]
                }]
        self.params=ptree.Parameter.create(name='Functions', type='group', children=children)
        self.selectionTree.setParameters(self.params)
        self.params.param('Graph setup', 'New axis').sigActivated.connect(self.newGraphGrid)
        self.params.param('Graph setup', 'Set axis').sigActivated.connect(self.setGraphGrid)
        self.params.param('Curves functions', 'Add curve').sigActivated.connect(self.addCurve)
        custom_functions.set_Param_opts(self.params,table=[('Graph setup'),('Curves functions')],visible=False,
                                        enabled=False)
        self.ExportB.clicked.connect(lambda: print(self.Get_Params_index(self.params)))
        self.plotgraph.scene().sigMouseClicked.connect(self.mouse_clicked)
        self.params_indexes=dict()

    def mouse_clicked(self, event):

        if self.imgitem:
            if event.button() == QtCore.Qt.MouseButton.LeftButton :
                scene_coords = QtCore.QPointF(  event.pos().x()-self.roi.getState()['pos'].x(),
                                                event.pos().y()-self.roi.getState()['pos'].y())

                if self.graph_area is not None:
                    if self.graph_area.contains(scene_coords):
                        item=custom_functions.getItems(self.deviceTree)
                        if item.type is custom_types.itemType.CURVE:
                            event.accept()
                            self.UIsignals.emit((custom_types.qSignalType.ADD,(item,scene_coords)))
                            self.curves[self.curve_selected].graph.addPoint()
                        else:
                            event.ignore()

    def pasteImage(self):

        clipboard = QApplication.clipboard()
        mimedata=clipboard.mimeData().urls()
        if mimedata:
            #! plante si mimedata chargé avant le lancement
            path = mimedata[0].toLocalFile()
            self.loadFileDialog(fileType=custom_types.fileType.IMG,adress=[path])

    def keyPressEvent(self, event):

        if event.key() == QtCore.Qt.Key.Key_Delete | self.hasFocus():
            try:
                Qitem=self.getItems(self.componentTree)[0]
                id=self.componentTree.indexFromItem(Qitem)
                self.curves[id].graph['data']
                print('RESTE A FAIRE !!')
                #//TODO: utiliser les vrais état retour du messagebox (actuellement .exec
                #//TODO: retourne des int)
            except:
                pass
            event.accept()
        elif event.key() == QtCore.Qt.Key.Key_V and event.modifiers()==QtCore.Qt.KeyboardModifier.ControlModifier:
            print('in')
            self.pasteImage()
            event.accept()

    def dragEnterEvent(self, event):

        if event.mimeData().hasImage:
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasImage:
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasImage:
            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            path = event.mimeData().urls()[0].toLocalFile()
            print(path)
            self.loadFileDialog(fileType=custom_types.fileType.IMG,adress=[path])
            event.accept()
        else:
            event.ignore()

    def onItemClicked(self, it):
        #on récupère la courbe dont le tree_id correspond à l'item sélectionné
        pass
        '''id=[i for i,curve in enumerate(self.curves) if curve.QItem==it][0]
        self.curve_selected=id
        self.updateSelectionTree(id)'''
        #self.updateTableXY(id)

    def closeEvent(self, event):
        """
            Méthode gérant la fermeture de toutes les fenêtres annexes
        Args:
            event (QEvent): Evenement devant provoquer la fermeture de toutes
                            les fenêtres (ex: la fermeture de la MainWindow)
        """
        #ferme toutes les fenêtres annexes qui existent permettant de ferme le GL depuis la MW
        if self.windows_set:
            self.windows_set.close()

        if self.graphWindows:
            for window in self.graphWindows:
                window.close()

    '''
    def addCurve(self):
        #création d'un tronc par fichier
        #! custom ITEM
        parent = QTreeWidgetItem(self.componentTree)
        parent.setText(0, 'new curve')
        #ItemIsAutoTristate autorise un troisième état logique pour la checkbox :
        #lorsque qu'un ou plusieurs enfants sont sélectionner mais pas tous
        parent.setFlags(parent.flags() | QtCore.Qt.ItemFlag.ItemIsEditable |
                        QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsDropEnabled)
        if isinstance(self.graph_area,QGraphicsRectItem):
            self.curves.append(DigitizedCurve(item=parent,pen=pg.mkPen('r',width=1),
                                                brush=pg.mkColor('r'),scale=self.getParamScale(),
                                                origin=self.graph_area.rect().getCoords()))
            self.curves[-1].signal_emitter.model_signal.connect(self.addModel)
        else:
            self.curves.append(DigitizedCurve(item=parent,pen=pg.mkPen('r',width=1),
                                                brush=pg.mkColor('r')),
                                scale=self.getParamScale())

        self.plotgraph.addItem(self.curves[-1].graph)
        self.onItemClicked(parent)


    def addModel(self,it):

        id=[i for i,curve in enumerate(self.curves) if curve.QItem==it][0]
        #! custom ITEM
        mod=QTreeWidgetItem(it)
        mod.setText(0, 'Curve model')
        curve=pg.PlotDataItem(*self.curves[id].createModelCurve(),pen=pg.mkPen('r',width=1))
        self.plotgraph.addItem(curve)
        self.populateTable(self.curves[id].getXY())
        '''


    def populateTable(self,data):

        self.tableXY.setData(data)


    def GetUserScale(self):

        scale_window=WabDialogs.ScaleDialog(self.getParamScale())
        def emitChange(self):
            #!ajouter le QItem sélectionné
            self.UIsignals.emit((custom_types.qSignalType.SCALE,scale_window.getValues()))

        scale_window.accepted.connect(emitChange)

    def setGraphGrid(self):
        """
        Méthode permettant de définir la position des axes du graph
        """

        if self.roi:
            roi_params=self.roi.getState()
            #self.graph_area = QGraphicsRectItem(QtCore.QRectF(roi_params['pos'].x(),
            #                 roi_params['pos'].y(),roi_params['size'].x(),roi_params['size'].y()))
            self.graph_area = QGraphicsRectItem(QtCore.QRectF(0,0,roi_params['size'].x(),
                                                                roi_params['size'].y()))
            self.graph_area.setPen(pg.mkPen(100, 200, 100))
            self.axis_configured=True

            user_scale=self.GetUserScale()
            if user_scale is not None:
                tr = QtGui.QTransform()  #Objet transformation:
                #On replace l'image, de manière à faire coincider l'origine du graph avec l'origine
                #de la courbe numérisée
                tr.translate(-roi_params['pos'].x(),-roi_params['pos'].y())
                self.imgitem.setTransform(tr)
                self.setGridScale()
                self.plotgraph.addItem(self.graph_area)
                self.plotgraph.removeItem(self.roi)

    #! Récupérer la structure du paramètre sélectionné => QItem
    def getParamScale(self):
        _scale=list()
        for child in self.params.child('Graph setup','Set axis'):
            _scale.append(child.value())
        return _scale

    def setGridScale(self,item:custom_items.parameterTreeItem):
        """
        Méthode permettant de définir les caractéristiques (échelles) des axes du graph
        """

        #! Mise à l'échelle à revoir : la grille n'est pas à l'échelle de la courbe
        #! (self.roi ne doit pas avoir la même origine que le cadre une fois la
        #! transformation effectuée)
        print(f'Coordonnées : {item.struct.coordinate}')
        if item.struct.coordinate is not None and self.graph_area is not None:
            scale = item.struct.coordinate
            grid_params = self.graph_area.rect().getRect()
            graph_options = {}
            for child in self.params.child('Graph setup','Axis options'):
                key=child.name()
                graph_options[key]=child.value()

            xp_axis = self.plotgraph.getAxis('bottom')
            x_scale,y_scale = item.delta

            # mise à l'échelle par un simple produit en croix :
            # graduation divisé par le nombre de pixels
            xticks=[x_scale/scale.xtick,
                    x_scale/(scale.xtick*5)]
            xp_axis.setTickSpacing(xticks[0],xticks[1])

            xp_axis.setScale(x_scale/grid_params[2])
            ypaxis = self.plotgraph.getAxis('left')
            yticks=[y_scale/scale.ytick,
                    y_scale/(scale.ytick*5)]

            ypaxis.setTickSpacing(yticks[0],yticks[1])
            ypaxis.setScale(y_scale/grid_params[3])
            self.plotgraph.setLabel('bottom', scale.xlabel)
            self.plotgraph.setLabel('left', scale.ylabel)
            self.plotgraph.showGrid(x=True, y=True,alpha=0.3)
            self.plotgraph.setXRange(scale.xmin,scale.xmax)
            self.plotgraph.setYRange(scale.ymin,scale.ymax)
            self.plotgraph.vb.autoRange()
        else:
            pass

    def clearGraph(self):

        self.axis_configured=False
        self.plotgraph.clear()

    def loadGraph(self,item):

        img = QtGui.QImage(item.struct.adress)
        #img = img.convertToFormat(QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        imgArray = pg.imageToArray(img, copy=True,transpose=False)
        np_array=np.rot90(np.flip(imgArray,(1,0)))
        self.imgitem = pg.ImageItem(np_array)
        self.plotgraph.addItem(self.imgitem)
        self.imgitem.setZValue(-100)
        #range_ = self.plotgraph.getViewBox().viewRange()
        _shape=self.imgitem.image.shape
        xmin=-_shape[0]*0.1
        ymin=-_shape[1]*0.1
        xmax=_shape[0]*1.1
        ymax=_shape[1]*1.1
        self.plotgraph.setLimits(xMin=xmin,yMin=ymin,xMax=xmax,yMax=ymax)
        self.newGraphGrid(item)

    def newGraphGrid(self,item):

        print(item)
        if item.axis_configured == True:
            if not self.redefinedAxis():
                return -1
        if item.rect is None:
            width_box=150
            height_box=150
        else:
            width_box=item.rect[0]
            height_box=item.rect[1]

        if self.imgitem is None:
            pass
        else:
            x_root=(self.imgitem.width()-width_box)/2
            y_root=(self.imgitem.height()-height_box)/2
            self.roi=pg.RectROI(pos=(x_root,y_root),size=(width_box,height_box),pen=pg.mkPen('r',width=1))
            self.roi.addScaleHandle(pos=[0, 0],center=[1,1])
            self.roi.addScaleHandle(pos=[1, 0],center=[0,1])
            self.roi.addScaleHandle(pos=[0, 1],center=[1,0])
            self.plotgraph.addItem(self.roi)

    def getParameters(self,key=None):
        if key is None:
            return [self.params.child(*index).value() for key,index in self.parameters_indexes.items()]
        else:
            return self.params.child(*self.parameters_indexes[key]).value()

    #! demande à l'utilisateur s'il souhaite redéfinir les axes. A REVOIR
    @staticmethod
    def redefinedAxis():

        reply = QMessageBox.question(   icon = QMessageBox.Icon.Information,
                                title="Existing axis",
                                text= "Axis are already defined. Do you want to set new ones ?",
                                buttons= 'QMessageBox.StandardButton')

        if reply == QMessageBox.StandardButton.Yes:
            return True
        else:
            return False

    def highlight(self,item,curve):
        """
        Méthode sur évènement (sélection d'un item), permettant de mettre en évidence
        la courbe correspondante
        Arguments:
                item   {QTreeWidgetItem}   -- item sélectionné
                curve  {PlotItem}          -- courbe correspondante
        Returns:
                None                       -- MAJ du graph
        """
        #Augmente la largeur de la courve et la remonte au-dessus des autres plotitems : Zval = 10
        if curve is not None:
            custom_functions.updateCurve(curve,width = 3,z_val = 10)
        custom_functions.setItemFont(item,bold = True)
        def recursiveExpension(treeItem):
            if treeItem.parent():
                parent_item = treeItem.parent()
                parent_item.setExpanded(True)
                recursiveExpension(parent_item)
        recursiveExpension(item)
        #si l'on vient de sélectionner une nouvelle courbe et que l'ancienne courbe a été définie
        #au moins une fois
        if self.old_highlight != (item,curve):
            if self.old_highlight[1] is not None:
                custom_functions.updateCurve(self.old_highlight[1])

            if self.old_highlight[0] is not None:
                custom_functions.setItemFont(self.old_highlight[0],bold = False)
                if self.old_highlight[0].type is not custom_types.itemType.FILE:
                    self.old_highlight[0].struct.pen.setWidth(1)
                #! écrase la valeur sauvegardée dans l'item afin de ne pas recharger l'ancienne
                #! valeur de 3.

        self.old_highlight = (item,curve)

    def addText(self,parent=None,pos=None):
        """_summary_
        """
        text = WabDialogs.PgText()
        text.textEditor()
        self.plotgraph.addItem(text)
        if parent is not None:
            text.setParentItem(parent)
        else:
            text.setParentItem(self.plotgraph.vb)

        if pos is not None:
            text.setPos(pos)
        else:
            text.setPos(QtCore.QPointF(375,250))


    def treeMenu(self):
        """
        Méthode vide qui sera décrite par la classe héritant de GLWindow
        """
        pass

    def mouseMoved(self,evt):
        """
        Méthode vide qui sera décrite par la classe héritant de GLWindow
        """
        pass


    def loadFileDialog(self,fileType=custom_types.fileType.IMG,adress = None):
        """
        Méthode gérant la fenêtre de dialogue permettant de charger des fichiers .CSV
        de type GLviewer dans l'appli.

        Arguments:
                adress      --
                fileType    --
        Returns:
                None        --
        """
        load_dict = {custom_types.fileType.CSV:("Opening .CSV files","csv Files (*.csv)"),
                    custom_types.fileType.XML:("Opening .XML model files","XML Files (*.XML)"),
                    custom_types.fileType.IMG:("Load graph image","Image Files (*.png *.jpg *.jpeg *.bmp)")}

        if adress:
            fnames = adress
        else:
            message,file_extension = load_dict[fileType]
            self.statusbar.showMessage(message)
            fnames,_ = QFileDialog.getOpenFileNames(self,message,"",file_extension)
            if not fnames:
                return

        for fname in fnames:
            if fname:
                name = fname[fname.rfind('/')+1:len(fname)-4]
                existing_file = [self.componentTree.topLevelItem(i).text(0)
                                for i in range(self.componentTree.topLevelItemCount())]
                if name in existing_file:
                    self.statusbar.showMessage(f"File: {fname} already loaded")
                    continue
                self.statusbar.showMessage(f"Loading : {fname}")
                #?ne charge qu'un seul fichier par appel afin de retirer les fichiers
                #?déjà chargés de la liste fnames (la méthode pourrait charger fnames).
                #! EMIT loadFile_signal.SIGNAL!
                self.loadFile_signal.emit((fileType,[fname]))