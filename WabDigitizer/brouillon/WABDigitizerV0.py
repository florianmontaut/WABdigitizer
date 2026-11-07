from PyQt6.QtCore import QEvent, QObject,pyqtSignal
from PyQt6.QtWidgets import QApplication, QMainWindow, QGraphicsRectItem,QFileDialog,QMenu,QTreeWidgetItem,QTreeWidgetItemIterator,QTreeWidget,QPushButton,QCheckBox,QMessageBox
from PyQt6 import QtGui,QtCore,QtWidgets
from PyQt6.uic import loadUi
from GLWindows import ScaleDialog
import numpy as np
import pyqtgraph as pg
import pyqtgraph.parametertree as ptree
import pyqtgraph.parametertree.parameterTypes as pTypes
from pyqtgraph.graphicsItems.ScatterPlotItem import name_list
from scipy.optimize import curve_fit
from MaskPainter import MaskPainter
import sys  # We need sys so that we can pass argv to QApplication


from coordinate_transformer import CoordinateTransformer
from averaging_window_extractor import AveragingWindowExtractor
from custom_independent_extractor import CustomIndependentExtractor



class MySignalEmitter(QObject):
    # Define a custom signal with a value
    #! remplaçable par un simple évènement sur la modification du parameterTree:
    #! MAJ du paramètre model => la fonction connectée au signal "sigTreeStateChanged" du maingraph pourrait récupère la valeur du modèle
    model_signal = pyqtSignal(QTreeWidgetItem)
    MAJ_curve_signal=pyqtSignal()


class MainWindow(QMainWindow):

    def __init__(self):
        super(MainWindow, self).__init__()
        #Load the UI Page
        loadUi('./brouillon/WABDigitizer_V0.ui', self)

        #initialisation des variables et tables:
        self.selected_curve=[None,None]   #flag pour la remise à l'état initial d'une courbe qui n'est plus sélectionné sur le graph
        self.old_highlight=None           #dernier item sélectionné, utilisé par la fonction Highlight permettant de surligner la courbe correspondant à la selection dans le treewidget
        self.modeltree:QTreeWidget         #affection de l'argument treefile au type QTreeWidget afin de bénificier de l'autocomplétion/suggestion lors de l'écriture du code
        self.imgitem=None
        self.axis_configured=False
        self.curves=list()
        self.setAcceptDrops(True)

        self.maskPainter = MaskPainter()
        self.averagingExtractor = AveragingWindowExtractor(
                                                                x_step=8,
                                                                y_step=8
                                                            )

        self.customIndependentExtractor = CustomIndependentExtractor(
                                                                        curve_width_px=5,
                                                                        x_step_px=5,
                                                                        y_step_px=5,
                                                                        allow_extrapolation=False
                                                                    )


        #self.modeltree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        #Ajout de la création d'un treemenu lors d'un clic dans le widget treefile
        #self.modeltree.customContextMenuRequested.connect(self.treeMenu)
        #Réglage de l'affichage principal
        self.plotgraph=self.maingraph.addPlot(row=0, col=0) #plotgraph est un graphiclayoutwidget, on ajoute un plot maingraph en position 0,0 du layout plotgraph
        self.maingraph.setBackground('lightgray')                   #passage du maingraph en fond blanc
        self.modeltree.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection) #configuration de la sélection en mode single
        self.modeltree.hideColumn(2)                                                                 #cache la colonne id

        #self.modeltree.itemClicked.connect(self.onItemClicked)                                       #Ajout du peuplement du parameter tree + mise en évidence de la courbe correspondante lorsqu'un item du treefile est sélectionné
        self.actionMask = QtGui.QAction("Mask Painter", self)
        self.actionMask.setCheckable(True)
        self.menuBar().addAction(self.actionMask)  # Or add to existing menu
        #Ajout des actions du menu principal
        self.actiongraph.triggered.connect(self.loadGraph)
        self.actionmodel.triggered.connect(self.loadGraph)
        self.actionQuit.triggered.connect(self.close)

        self.actionExtractCurve = QtGui.QAction("Auto Extract Curve",self)
        self.menuBar().addAction(self.actionExtractCurve)
        self.actionMask.triggered.connect(self.toggleMaskPainter)
        self.actionExtractCurve.triggered.connect(self.autoExtractCurve)


        self.modeltree.itemClicked.connect(self.onItemClicked)

        #ajout du TableWidget "à la main" car la fonction load.ui n'arrive pas à créer cet objet (loadUI passe un objet parent à TableWidget, qui n'en attend pas )
        self.tableXY=pg.TableWidget(editable=True,sortable=False)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(5)
        sizePolicy.setHeightForWidth(self.tableXY.sizePolicy().hasHeightForWidth())
        self.tableXY.setSizePolicy(sizePolicy)
        self.splitter_3.setOrientation(QtCore.Qt.Orientation.Vertical)
        self.splitter_3.addWidget(self.tableXY)
        self.drawing = False
        self.brush_thickness    = 10                                    # Default brush thickness
        self.brush_color        = QtGui.QColor('red')                   # Default brush color
        self.brush_style        = QtCore.Qt.BrushStyle.SolidPattern     # Default brush style




        #//TODO: ajouter self.plotgraph.scene().signal pour récupérer les doubles clics dans la ROI => création d'un point / supression d'un point
        #self.plotgraph.hideAxis(axis='bottom')
        #self.plotgraph.hideAxis(axis='left')
        """
        self.tableXY.setColumnWidth(0,80)
        self.tableXY.setColumnWidth(1,80)"""

        child= [{'name': 'Graph setup', 'type': 'group', 'children':
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
                },
                {
                    'name': 'Auto extraction',
                    'type': 'group',
                    'children': [
                        {
                            'name': 'Extraction method',
                            'type': 'list',
                            'values': [
                                'Skeleton',
                                'Averaging Window',
                                'Custom Independents'
                            ],
                            'value': 'Custom Independents'
                        },
                        {
                            'name': 'Averaging X step px',
                            'type': 'float',
                            'value': 8.0,
                            'limits': [1.0, None]
                        },
                        {
                            'name': 'Averaging Y step px',
                            'type': 'float',
                            'value': 8.0,
                            'limits': [1.0, None]
                        },
                        {
                            'name': 'Curve width px',
                            'type': 'float',
                            'value': 5.0,
                            'limits': [0.0, None]
                        },
                        {
                            'name': 'Custom X start',
                            'type': 'float',
                            'value': 0.0
                        },
                        {
                            'name': 'Custom X stop',
                            'type': 'float',
                            'value': 100.0
                        },
                        {
                            'name': 'Custom X step',
                            'type': 'float',
                            'value': 5.0,
                            'limits': [1e-12, None]
                        },
                        {
                            'name': 'Allow extrapolation',
                            'type': 'bool',
                            'value': False
                        }
                    ]
                }

                ]

        self.params=ptree.Parameter.create(name='Functions', type='group', children=child)
        self.selectiontree.setParameters(self.params)

        self.params.param('Graph setup', 'New axis').sigActivated.connect(self.newGraphGrid)
        self.params.param('Graph setup', 'Set axis').sigActivated.connect(self.setGraphGrid)
        self.params.param('Curves functions', 'Add curve').sigActivated.connect(self.addCurve)

        self.set_Param_opts(self.params,table=[('Graph setup'),('Curves functions')],visible=False,enabled=False)
        self.ExportB.clicked.connect(lambda: print(self.Get_Params_index(self.params)))
        self.plotgraph.scene().sigMouseClicked.connect(self.mousePressEvent)
        self.params_indexes=dict()

        #self.params.sigTreeStateChanged.connect(self.setGridScale)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.drawing:
            painter = QtGui.QPainter(self)
            pen = QtGui.QPen(self.brush_color, self.brush_thickness, QtCore.Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(self.brush_color, self.brush_style))
            painter.drawEllipse(self.lastPos, self.brush_thickness // 2, self.brush_thickness // 2)
            painter.end()


    ########################## Mouse Events from vid #########################
    def mousePressEvent(self, event):

        if self.imgitem:
            if event.button() == QtCore.Qt.MouseButton.LeftButton :
                if self.drawing==True:
                    self.lastPoint = event.pos()
                else:
                    scene_coords = QtCore.QPointF(event.pos().x()-self.roi.getState()['pos'].x(),event.pos().y()-self.roi.getState()['pos'].y())
                    if self.graph_area:
                        if self.graph_area.contains(scene_coords):

                            self.curves[self.curve_selected].graph.addPoint(scene_coords)
        event.ignore()

    def mouseMouvedEvent(self, event):
        if (event.button() & QtCore.Qt.MouseButton.LeftButton) and self.drawing:
            self.lastPos = event.pos()
            self.update()  # Trigger a repaint to show the brush effect

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self.drawing:
            self.drawing = False
    ########################## Mouse Events from vid #########################


    ############### Mask Painting Tool Functions
    #ollama
    ############
    def toggleMaskPainter(self, checked):
        """Toggle the mask painter on/off"""
        if checked:
            self.activateMaskPainter()
        else:
            self.deactivateMaskPainter()

    def deactivateMaskPainter(self):
        """
        Désactive l'outil de peinture du masque.
        """

        self.maskPainter.detachFromPlot()

        self.unsetCursor()

        try:
            self.plotgraph.scene().sigMouseClicked.connect(self.mouse_clicked)
        except Exception:
            pass

        self.statusbar.showMessage("Ready")

    ############

    
    def getCoordinateTransformer(self):
        """
        Construit un transformateur pixel <-> unités physiques
        à partir de la zone graphique et des paramètres d'axe.
        """

        if not isinstance(self.graph_area, QGraphicsRectItem):
            raise ValueError("Graph area is not defined.")
        origin = self.graph_area.rect().getCoords()
        scale = self.getParamScale()

        return CoordinateTransformer(
                                        plot_origin=origin,
                                        scale=scale
                                    )

    def getExtractionParams(self):
        """
        Récupère les paramètres du groupe Auto extraction.
        """

        group = self.params.child('Auto extraction')

        return {
            'method': group.child('Extraction method').value(),
            'avg_x_step': group.child('Averaging X step px').value(),
            'avg_y_step': group.child('Averaging Y step px').value(),
            'curve_width': group.child('Curve width px').value(),
            'custom_x_start': group.child('Custom X start').value(),
            'custom_x_stop': group.child('Custom X stop').value(),
            'custom_x_step': group.child('Custom X step').value(),
            'allow_extrapolation': group.child('Allow extrapolation').value()
        }

    def imagePointsToPlot(self, pointsImage):
        """
        Convertit des points [x, y] dans le repère local de imageItem
        vers le repère du PlotItem.

        La transformation appliquée par setGraphGrid() est donc prise en compte.
        """

        if self.imgitem is None:
            return np.empty((0, 2), dtype=float)

        result = []

        for x, y in pointsImage:
            p = self.imgitem.mapToParent(
                QtCore.QPointF(float(x), float(y))
            )

            result.append([p.x(), p.y()])

        return np.array(result, dtype=float)






    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key.Key_Delete | self.hasFocus():

            try:
                Qitem=self.getItems(self.modeltree)[0]
                id=self.modeltree.indexFromItem(Qitem)
                self.curves[id].graph['data']
                print('RESTE A FAIRE !!')
                #//TODO: utiliser les vrais état retour du messagebox (actuellement .exec retourne des int)
            except:
                pass
            event.accept()

        elif event.key() == QtCore.Qt.Key.Key_V and event.modifiers()==QtCore.Qt.KeyboardModifier.ControlModifier:
            self.paste_image()
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
            file_path = event.mimeData().urls()[0].toLocalFile()
            self.set_image(file_path)

            event.accept()
        else:
            event.ignore()

    def onItemClicked(self, it):
        id=[i for i,curve in enumerate(self.curves) if curve.QItem==it][0] #on récupère la courbe dont le tree_id correspond à l'item sélectionné
        self.curve_selected=id
        self.updateSelectionTree(id)
        #self.updateTableXY(id)

    def updateSelectionTree(self,id_curve):

        self.selectiontree.addParameters(self.curves[id_curve].curve_params)
        self.selected_curve=self.curves[id_curve]
        if self.selectiontree.topLevelItemCount()>2:
            self.selectiontree.takeTopLevelItem(1)
        #fonction interne qui va permettre de mettre à jour le style de la courbe, uniquement si les paramètres du selectiontree sont modifiés
        def update_plot():
            self.curves[id_curve].updateGraphColor()

        self.curves[id_curve].curve_params.sigTreeStateChanged.connect(update_plot)
        self.curves[id_curve].graph.scatter.sigPlotChanged.connect(self.updateTableXY)

    def updateTableXY(self):

        def update_points():
            """
            Fonction interne ajoutant les coordonnées XY dans la table d'affichage à chaque fois qu'un point est ajouté
            Arguments:
                    None  --
            Returns:
                    None  --

            Lorsque l'on modifie les points via le tableau il faut alors
            bloquer le signal de MAJ du graph sans quoi on rentre dans une boucle infinie
            """
            #self.tableXY.blockSignals(True)
            self.selected_curve.graph.scatter.blockSignals(True)
            points=self.selected_curve.setXY(np.row_stack([(float(self.tableXY.item(row,0).text()),float(self.tableXY.item(row,1).text())) for row in range(self.tableXY.rowCount())]))
            self.selected_curve.graph.setCurve(pos=points)
            #self.tableXY.blockSignals(False)
            self.selected_curve.graph.scatter.blockSignals(False)

        pos=self.selected_curve.graph.data['pos']
        self.tableXY.blockSignals(True)
        #self.selected_curve.graph.scatter.blockSignals(True)
        self.tableXY.setData(self.selected_curve.getXY())
        self.tableXY.blockSignals(False)
        #self.selected_curve.graph.scatter.blockSignals(False)
        self.tableXY.cellChanged.connect(update_points)




    def autoExtractCurve(self):
        """
        Extrait automatiquement une courbe selon l'algorithme choisi :

            - Skeleton
            - Averaging Window
            - Custom Independents

        Le mode Custom Independents retourne une courbe sur une grille
        d'abscisses physiques imposée.
        """

        if self.imgitem is None:
            QMessageBox.warning(
                self,
                "Extraction",
                "Aucune image n'est chargée."
            )
            return

        if self.selected_curve is None:
            QMessageBox.warning(
                self,
                "Extraction",
                "Aucune courbe sélectionnée."
            )
            return

        mask = self.maskPainter.getBinaryMask()

        if mask is None:
            QMessageBox.warning(
                self,
                "Extraction",
                "Aucun masque disponible."
            )
            return

        try:

            params = self.getExtractionParams()

            method = params['method']

            # ========================================================
            # 1) Skeleton : ton extracteur actuel
            # ========================================================

            if method == 'Skeleton':

                image = self.imgitem.image

                points_image = self.curveExtractor.extract(
                    image,
                    mask
                )

                if len(points_image) < 2:
                    QMessageBox.warning(
                        self,
                        "Extraction",
                        "Aucun point valide détecté."
                    )
                    return

                points_plot = self.imagePointsToPlot(
                    points_image
                )

                self.selected_curve.graph.setCurve(
                    pos=points_plot
                )

                self.updateTableXY()

                self.statusbar.showMessage(
                    f"Skeleton : {len(points_plot)} points extraits."
                )

                return

            # ========================================================
            # 2) Averaging Window
            # ========================================================

            if method == 'Averaging Window':

                self.averagingExtractor.x_step = params['avg_x_step']
                self.averagingExtractor.y_step = params['avg_y_step']

                points_image = self.averagingExtractor.extract(
                    mask
                )

                if len(points_image) < 2:
                    QMessageBox.warning(
                        self,
                        "Extraction",
                        "Aucun point valide détecté."
                    )
                    return

                points_plot = self.imagePointsToPlot(
                    points_image
                )

                self.selected_curve.graph.setCurve(
                    pos=points_plot
                )

                self.updateTableXY()

                self.statusbar.showMessage(
                    f"Averaging Window : {len(points_plot)} points extraits."
                )

                return

            # ========================================================
            # 3) Custom Independents
            # ========================================================

            if method == 'Custom Independents':

                transformer = self.getCoordinateTransformer()

                self.customIndependentExtractor.curve_width_px = params['curve_width']
                self.customIndependentExtractor.x_step_px = params['avg_x_step']
                self.customIndependentExtractor.y_step_px = params['avg_y_step']
                self.customIndependentExtractor.allow_extrapolation = params[
                    'allow_extrapolation'
                ]

                result_data = (
                    self.customIndependentExtractor.extract_uniform_grid(
                        binary_mask=mask,
                        coordinate_transformer=transformer,
                        xmin=params['custom_x_start'],
                        xmax=params['custom_x_stop'],
                        step=params['custom_x_step'],
                        image_to_plot_func=self.imagePointsToPlot
                    )
                )


                if len(result_data) < 2:
                    QMessageBox.warning(
                        self,
                        "Extraction",
                        "Aucun point valide extrait sur la grille imposée."
                    )
                    return

                points_plot = transformer.data_to_pixel(
                    result_data
                )

                self.selected_curve.graph.setCurve(
                    pos=points_plot
                )

                self.updateTableXY()

                self.statusbar.showMessage(
                    f"Custom Independents : {len(result_data)} points générés "
                    f"sur grille physique."
                )

                return

            QMessageBox.warning(
                self,
                "Extraction",
                f"Méthode inconnue : {method}"
            )

        except Exception as exc:

            QMessageBox.critical(
                self,
                "Extraction failed",
                str(exc)
            )



    def paste_image(self):

        clipboard = QApplication.clipboard()
        mimeData = clipboard.mimeData()
        if mimeData.hasImage():
            img=QtGui.QImage(mimeData.imageData())
            self.loadGraph(img=img)
        else :
            return

    def set_image(self, file_path):

        self.clearGraph()
        img = QtGui.QImage(QtGui.QPixmap(file_path))
        self.loadGraph(img=img)

    def addCurve(self):

        #création d'un tronc par fichier
        parent = QTreeWidgetItem(self.modeltree)
        parent.setText(0, 'new curve')
        #ItemIsAutoTristate autorise un troisième état logique pour la checkbox : lorsque qu'un ou plusieurs enfants sont sélectionner mais pas tous
        parent.setFlags(parent.flags() | QtCore.Qt.ItemFlag.ItemIsEditable | QtCore.Qt.ItemFlag.ItemIsDragEnabled | QtCore.Qt.ItemFlag.ItemIsDropEnabled)
        if isinstance(self.graph_area,QGraphicsRectItem):
            self.curves.append(DigitizedCurve(item=parent,pen=pg.mkPen('r',width=1),brush=pg.mkColor('r'),scale=self.getParamScale(),
                                                origin=self.graph_area.rect().getCoords()))
            self.curves[-1].signal_emitter.model_signal.connect(self.addModel)
        else:
            self.curves.append(DigitizedCurve(item=parent,pen=pg.mkPen('r',width=1),brush=pg.mkColor('r')),
                                scale=self.getParamScale())

        self.plotgraph.addItem(self.curves[-1].graph)
        self.onItemClicked(parent)

    def populateTable(self,data):

        self.tableXY.setData(data)

    def addModel(self,it):

        id=[i for i,curve in enumerate(self.curves) if curve.QItem==it][0]
        mod=QTreeWidgetItem(it)
        mod.setText(0, 'Curve model')
        curve=pg.PlotDataItem(*self.curves[id].createModelCurve(),pen=pg.mkPen('r',width=1))
        self.plotgraph.addItem(curve)
        self.populateTable(self.curves[id].getXY())

    def setGraphGrid(self):

        if self.roi:
            roi_params=self.roi.getState()
            #self.graph_area = QtWidgets.QGraphicsRectItem(QtCore.QRectF(roi_params['pos'].x(),roi_params['pos'].y(),roi_params['size'].x(),roi_params['size'].y()))
            self.graph_area = QtWidgets.QGraphicsRectItem(QtCore.QRectF(0,0,roi_params['size'].x(),roi_params['size'].y()))
            self.graph_area.setPen(pg.mkPen(100, 200, 100))
            self.axis_configured=True

            user_cancel=self.GetUserScale()
            if user_cancel is False:
                tr = QtGui.QTransform()  #Objet transformation:
                tr.translate(-roi_params['pos'].x(),-roi_params['pos'].y()) #On replace l'image de manière à faire coincider l'origine du graph avec l'origine de la courbe numérisée
                self.imgitem.setTransform(tr)
                self.setGridScale()
                self.plotgraph.addItem(self.graph_area)
                self.plotgraph.removeItem(self.roi)



    def getParamScale(self):
        _scale=list()
        for child in self.params.child('Graph setup','Set axis'):
            _scale.append(child.value())
        return _scale

    def GetUserScale(self):

        _scale=self.getParamScale()
        scale_window=ScaleDialog(Xmin=_scale[0],Xmax=_scale[1],Ymin=_scale[2],Ymax=_scale[3],logX=_scale[4],logY=_scale[5])
        if scale_window.exec()==1: #si OK est pressé  dans la dialogBox, on récupère les données
            _scale=scale_window.getValues()
            #! récupérer la création du dict à partir d'un parameter tree => TTPmacro
            for i,child in enumerate(self.params.child('Graph setup','Set axis')):
                child.setValue(_scale[i])
                child.setDefault(_scale[i])
            self.set_Param_opts(self.params,table=[('Curves functions')],visible=True,enabled=True)
            self.addCurve()
            return False
        else:
            return True

    def setGridScale(self):

        #! Mise à l'échelle à revoir : la grille n'est pas à l'échelle de la courbe (self.roi ne doit pas avoir la même origine que le cadre une fois la transformation effectuée)
        _scale=self.getParamScale()
        grid_params=self.graph_area.rect().getRect()
        graph_options={}
        for child in self.params.child('Graph setup','Axis options'):
            key=child.name()
            graph_options[key]=child.value()

        xp_axis = self.plotgraph.getAxis('bottom')
        x_scale=_scale[1]-_scale[0]
        y_scale=_scale[3]-_scale[2]

        xticks=[x_scale/graph_options['X Tick number'],x_scale/(graph_options['X Tick number']*5)]
        xp_axis.setTickSpacing(xticks[0],xticks[1])
        xp_axis.setScale(x_scale/grid_params[2]) # mise à l'échelle par un simple produit en croix : graduation divisé par le nombre de pixels
        ypaxis = self.plotgraph.getAxis('left')
        yticks=[y_scale/(graph_options['Y Tick number']),y_scale/(graph_options['Y Tick number']*5)]
        ypaxis.setTickSpacing(yticks[0],yticks[1])
        ypaxis.setScale(y_scale/grid_params[3])
        self.plotgraph.setLabel('bottom', graph_options['X axis label'])
        self.plotgraph.setLabel('left',graph_options['Y axis label'])
        self.plotgraph.showGrid(x=True, y=True,alpha=0.3)
        self.plotgraph.setXRange(_scale[0],_scale[1])
        self.plotgraph.setYRange(_scale[2],_scale[3])
        self.plotgraph.vb.autoRange()

    def clearGraph(self):

        self.axis_configured=False
        self.plotgraph.clear()

    def loadGraph(self,img=None):

        self.clearGraph()
        if not img :
            self.statusbar.showMessage("Load graphic picture")
            gname,_=QFileDialog.getOpenFileName(self,"Load graph image","","Image Files (*.png *.jpg *.jpeg *.bmp)")
            img = QtGui.QImage(gname)
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
        self.newGraphGrid(_shape)
        #self.plotgraph.setAspectLocked(True,None)
        self.set_Param_opts(self.params,table=[('Graph setup')],visible=True,enabled=True)


    def activateMaskPainter(self):
        """
        Active l'outil de peinture du masque.
        """

        if self.imgitem is None:
            QMessageBox.warning(self,"Mask Painter","Aucune image n'est chargée." )
            self.actionMask.setChecked(False)
            return

        try:
            self.plotgraph.scene().sigMouseClicked.disconnect(self.mouse_clicked)
        except Exception:
            pass

        self.maskPainter.attachToPlot(self.plotgraph,self.imgitem)
        self.setCursor(QtCore.Qt.CursorShape.CrossCursor)

        self.statusbar.showMessage( "Mask Painter activated - left drag to paint,"+
                                    "right click to clear." )


    def newGraphGrid(self,_shape=None):

        if self.axis_configured == True:
            if self.definedAxis()==False:
                return -1
        if not _shape :
            width_box=150
            height_box=150
        else:
            width_box=_shape[0]
            height_box=_shape[1]

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
            self.axis_configured=True

    def getParameters(self,key=None):
        if key is None:
            return [self.params.child(*index).value() for key,index in self.parameters_indexes.items()]
        else:
            return self.params.child(*self.parameters_indexes[key]).value()

    @staticmethod
    def definedAxis():
        msgBox = QMessageBox()
        msgBox.setIcon(QMessageBox.Icon.Information)
        msgBox.setText("Axis are already defined. Do you want to set new ones ?")
        msgBox.setWindowTitle("Existing axis")
        msgBox.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        returnValue = msgBox.exec()

        if returnValue == 16384: #16384 = Yes / 65536 = No
            #//TODO: utiliser les vrais état retour du messagebox (actuellement .exec retourne des int)
            return True
        else:
            return False

    @staticmethod
    def getItems(tree:QTreeWidget) -> list[QTreeWidgetItem]:

        return tree.selectedItems()


    @staticmethod
    def set_Param_opts(paramaters,table,state=False,**opts):

        def recursive_search(field):
            """
            Méthode permettant de définir les options des champs d'un parameter tree et de modifier leurs options

            Arguments:
                    field {str or tuple}  -- clés permettant de scrupter les valeurs des champs correspondants
            Returns:
                    user_data {dict}   -- Dictionnaire contenant les informations nécessaire pour paramétrer l'objet HVAC
            """
            if isinstance(field,tuple):
                if paramaters.child(*field).hasChildren():
                    for key in paramaters.child(*field).keys():
                        new_key=(*field,key)
                        paramaters.child(*new_key).setOpts(**opts)
                        if paramaters.child(*new_key).hasChildren():
                            recursive_search(new_key)
                else:
                    paramaters.child(*new_key).setOpts(**opts)
            else:
                if paramaters.child(field).hasChildren():
                    for key in paramaters.child(field).keys():
                        if isinstance(field,str):
                            new_key=(field,key)
                        else:
                            new_key=(*field,key)
                        paramaters.child(*new_key).setOpts(**opts)

                        if paramaters.child(*new_key).hasChildren():
                            recursive_search(new_key)
                else:
                    paramaters.child(*new_key).setOpts(**opts)
        for param in table:
            recursive_search(param)

    @staticmethod
    def Get_Params_index(data):
        """
        Méthode permettant d'envoyer les données entrées par l'utilisateur dans le parametrerTree vers l'object HVAC qui servira de modèle pour la simulation

        """
        params_dict=dict()
        def recursive_search(parent_item):
            """
            Méthode permettant de récupérer l'ensemble des champs d'un parameter tree et de les renvoyer sous forme de liste (les champs dont la valeur est nulle sont ignorés)

            Arguments:
                    parent_item {str or tuple}  -- clés permettant de scrupter les valeurs des champs correspondants
            Returns:
                    user_data {dict}   -- Dictionnaire contenant les informations nécessaire pour paramétrer l'objet HVAC
            """

            if isinstance(parent_item,tuple):
                if data.child(*parent_item).hasChildren():
                    for key in data.child(*parent_item).keys():
                        new_key=(*parent_item,key)
                        val=data.child(*new_key).value()
                        if val is not None:
                            params_dict[key]=new_key
                        if data.child(*new_key).hasChildren():
                            recursive_search(new_key)
                else:
                    params_dict[data.child(parent_item).keys()[0]]=parent_item
            else:
                if data.child(parent_item).hasChildren():
                    for key in data.child(parent_item).keys():

                        if isinstance(parent_item,str):
                            new_key=(parent_item,key)
                        else:
                            new_key=(*parent_item,key)
                        val=data.child(*new_key).value()
                        if val is not None:
                            params_dict[key]=new_key
                        if data.child(*new_key).hasChildren():
                            recursive_search(new_key)
                else:
                    params_dict[data.child(parent_item).keys()[0]]=parent_item

            return params_dict


        #le dictionnaire params_dict ajoute les (keys/values) à chaque recursive_search
        for val in data.keys():
            recursive_search(val)
        return params_dict

class Graph(pg.GraphItem):

    def __init__(self,init_x,init_y):
        self.origin_x=init_x
        self.origin_y=init_y
        self.dragPoint = None
        self.dragOffset_x = None
        self.dragOffset_y = None
        pg.GraphItem.__init__(self)
        self.signal_emitter = MySignalEmitter()
        self.signal_emitter.MAJ_curve_signal.emit()
        self.hoverable=True
        self.block_add_point=False



    def clickEvent(self, event,pts):

            print(pts)
            if pts:
                self.block_add_point=True
            else:
                self.block_add_point=False

    def addPoint(self,loc):

        pos=np.array([loc.x(),loc.y()],ndmin=2)
        #si la clé 'pos' existe dans le dictionnaire data (càd que le scatterplot a des points) alors:
        if 'pos' in self.data :
            #si la position pos n'est pas présente dans la liste des points déjà existant alors on ajoute ce point:
            if not pos in self.data['pos']:

                pos=np.concatenate((self.data['pos'],pos),axis = 0)
            else:
                pos=self.data['pos']
        else:

            x = np.linspace(0, 100, 2)
            pos = np.column_stack((x+self.origin_x, x+self.origin_y))
            self.setData(pos=pos, hoverable=True,pxMode=True)


        self.setData(pos=pos, pxMode=True,hoverable=True,hoverPen=pg.mkPen('g',width=2))


    def setCurve(self,**kwds):

        self.data.update(kwds)
        if 'pos' in kwds:
            self.setData(pos=kwds['pos'], pxMode=True,hoverable=True,hoverPen=pg.mkPen('g',width=2))
        else:
            self.updateGraph()

    def setData(self, **kwds):

        #on trie les points par X croissant : permet de rajouter un point dans la courbe sans faire revenir la courbe en arrière
        #cette opération se fait uniquement à lors de l'ajout d'un point. L'essai de la maj après un évènement de drag&drop provoque le déplacement des points intervertis
        #après le tri selon les X (il faudrait mettre à jour l'indice du point sélectionné en fonction de son abscisse)
        if 'pos' in kwds:
            pos=kwds['pos']
            kwds['pos']=pos[pos[:,0].argsort()]

        self.data = kwds

        if 'pos' in self.data:

            npts = self.data['pos'].shape[0]
            self.data['data'] = np.empty(npts, dtype=[('index', int)])
            if npts>1:
                self.data['adj'] = np.column_stack((np.arange(0, npts-1), np.arange(1, npts)))
                self.data['data']['index'] = np.arange(npts)

        self.updateGraph()

    def updateGraph(self):

        pg.GraphItem.setData(self, **self.data)

    def mouseDragEvent(self, ev):

        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            ev.ignore()
            return

        if ev.isStart():
            pos = ev.buttonDownPos()
            pts = self.scatter.pointsAt(pos)
            if len(pts) == 0:
                ev.ignore()
                return
            self.dragPoint = pts[0]
            ind = pts[0].data()[0]
            self.dragOffset_x = self.data['pos'][ind][0] - pos[0]
            self.dragOffset_y = self.data['pos'][ind][1] - pos[1]

        elif ev.isFinish():
            self.dragPoint = None
            return
        else:
            if self.dragPoint is None:
                ev.ignore()
                return

        ind = self.dragPoint.data()[0]
        self.data['pos'][ind][0] = ev.pos()[0] + self.dragOffset_x
        self.data['pos'][ind][1] = ev.pos()[1] + self.dragOffset_y
        self.updateGraph()
        ev.accept()

    def getData(self,index=None):

        if index is None:
            return self.data['pos']
        else:
            return self.data['pos'][index]

class hidden_param(pTypes.GroupParameter):
    def __init__(self,n_max=6, **opts):
        model_keys= ['1st_order','2st_order','exp','polynomial']
        pTypes.GroupParameter.__init__(self, **opts)
        self.addChild({'name': 'Function', 'type': 'list','values':model_keys})
        self.addChild({'name': 'Polynomial Degree', 'type': 'int','limits':[1, n_max], 'value': 3,'visible':False})

        self.a = self.param('Function')
        self.b = self.param('Polynomial Degree')
        self.a.sigValueChanged.connect(self.aChanged)


    def aChanged(self):
        if self.a.value() =='polynomial':
            self.b.setOpts(visible=True)
        else:
            self.b.setOpts(visible=False)

class DigitizedCurve():

    def __init__(self,item,pen,brush,origin,scale=None,data=None) -> None:
        self.QItem=item          #item du modeltree
        self.data=data           #donnée de la courbe (x,y)
        self.curve_model=None

        self.signal_emitter = MySignalEmitter()

        if origin is None:
            self.origin=[0,0,100,100] # coordonnées d'un QRect: x0,x0,dX,dY
        else:
            self.origin=origin

        if scale is None:
            self.scale=[0,1,0,1,False,False] #Xmin,Xmax,Ymin,Ymax,Xlog?,Ylog?
        else:
            self.scale=scale

        self.updateScale()
        self.graph=Graph(init_x=origin[0],init_y=origin[1])


        def model_exp(x,c0,c1,c2,c3):

            if isinstance(x,list):
                return [c0+c1*i-c2*np.exp(-(i)/c3) for i in x]
            else:
                z= c0+c1*x-c2*np.exp(-(x)/c3)
            return z

        def model_1st_order(x,a,tau,b):

            if isinstance(x,list):

                res=[a*(1+b*i)*(1-np.exp(-(i)/tau)) for i in x]

                return res
            else:
                z=a*(1+b*x)*(1-np.exp(-(x)/tau))

                return z

        def model_2nd_order(x, a,tau,theta,b):
            S=np.empty(len(x))
            z=a*(1+b*x)*(1-np.exp(-(x-theta)/tau))

            for i in range(len(x)):
                if x[i]<theta: #attention vérifier, t[i] a été remplacé par x[i] => il faudrait plutôt charger l'index de la dataframe
                    S[i]=0
                else:
                    S[i]=1
            return z

        self.model={'1st_order': model_1st_order,'2st_order': model_2nd_order,'exp':model_exp}

        children = [{'name':'Curve color', 'type':'pen', 'value':pen,'expanded':False},
                    {'name':'Symbol parameters','type':'group','expanded':False,'children':
                        [
                        {'name':'Symbol shape','type':"list", 'values':name_list},
                        {'name':'Symbol color','type':'color', 'value':brush},
                        {'name':'Symbol size','type':"int", 'limits':[1,100],'value':20},
                        ]},
                    {'name':'Infos','type':'str','value':""},
                    {'name':'Model parameters','type': 'group','children':
                        [
                        {'name':'Create model','type':'action'},
                        hidden_param(name='Model'),
                        {'name':'Model coefficient','type':'float', 'value':0,'readonly':True},
                        {'name':'Show modeling curve','type':"bool", 'values':True},
                        ]},
                    ]

        self.curve_params = ptree.Parameter.create(name='Curve Parameters', type='group', children=children)
        self.curve_params.param('Model parameters','Create model').sigActivated.connect(self.getModel)
        self.updateGraphColor()



    @property
    def curve_color(self):
        return self.curve_params.child('Curve color').value()

    @property
    def symbol_shape(self):
        return self.curve_params.child('Symbol parameters','Symbol shape').value()

    @property
    def symbol_color(self):
        return self.curve_params.child('Symbol parameters','Symbol color').value()

    @property
    def symbol_size(self):
        return self.curve_params.child('Symbol parameters','Symbol size').value()

    @property
    def symbol_size(self):
        return self.curve_params.child('Symbol parameters','Symbol size').value()

    @property
    def model_type(self):
        return self.curve_params.child('Model parameters','Model','Function').value()

    @property
    def polynomial_deg(self):
        return self.curve_params.child('Model parameters','Model','Polynomial Degree').value()

    @property
    def offset_grid(self): #le décalage de l'image doit rendre l'offset inutile dorénavant
        npts=self.graph.getData().shape[0]
        return np.column_stack((np.ones(npts)*self.origin[0],np.ones(npts)*self.origin[1]))

    @property
    def offset_scale(self):
        npts=self.graph.getData().shape[0]
        return np.column_stack((self._offset_scale[0]*np.ones(npts),self._offset_scale[1]*np.ones(npts)))

    @property
    def delta(self):
        npts=self.graph.getData().shape[0]
        return np.column_stack((self._delta[0]*np.ones(npts),self._delta[1]*np.ones(npts)))

    def updateScale(self):

        if self.scale[4]==True:#Xlog?
            offset_dx=np.log10(self.scale[0])
            dx=(np.log10(self.scale[1]/self.scale[0]))/(self.origin[2]-self.origin[0])
        else:
            offset_dx=self.scale[0]
            dx=(self.scale[1]-self.scale[0])/(self.origin[2]-self.origin[0])

        if self.scale[5]==True:#Ylog?
            offset_dy=np.log10(self.scale[2])
            dy=(np.log10(self.scale[3]/self.scale[2]))/(self.origin[3]-self.origin[1]) #echelle log sur l'ordonnée
        else:
            offset_dy=self.scale[2]
            dy=(self.scale[3]-self.scale[2])/(self.origin[3]-self.origin[1])

        self._offset_scale=(offset_dx,offset_dy)
        self._delta=(dx,dy)

    def updateGraphColor(self):

        self.graph.setCurve(pen=self.curve_color,symbol=self.symbol_shape,symbolBrush=self.symbol_color,size=self.symbol_size)

    def setXY(self,pos):

        if self.scale[4]==False and self.scale[5]==False: #échelles linéaires

            return self.offset_grid+(pos-self.offset_scale)/self.delta

        res_log=self.offset_grid+(np.log10(pos)-self.offset_scale)/self.delta

        if self.scale[4]==True and self.scale[5]==True: #échelles logs

            return res_log

        res_lin=self.offset_grid+(pos-self.offset_scale)/self.delta

        if self.scale[4]==True: #seule l'abscisse est en log
            return np.concatenate((res_log[:,[0]],res_lin[:,[1]]),axis=1)

        else: #seule l'ordonnée est en log
            return np.concatenate((res_lin[:,[0]],res_log[:,[1]]),axis=1)


    def getXY(self):
        """
        Retourne les points graph mis à l'échelle. Approche vectorielle : liste de tuple [(x0,y0),(x1,y1)...(xn,yn)]
        Returns:
            _type_: _description_
        """
        if self.scale[4]==False and self.scale[5]==False:

            return (self.graph.getData()-self.offset_grid)*self.delta+self.offset_scale

        if self.scale[4]==True and self.scale[5]==True:

            return np.power(10,(self.graph.getData()-self.offset_grid)*self.delta+self.offset_scale)

        res_log=np.power(10,(self.graph.getData()-self.offset_grid)*self.delta+self.offset_scale)
        res_lin=(self.graph.getData()-self.offset_grid)*self.delta+self.offset_scale

        if self.scale[4]==True: #seulement l'abscisse est en log
            return np.concatenate((res_log[:,[0]],res_lin[:,[1]]),axis=1)   #mettre le numéro de colonne entre crôchet permet de récupérer un vecteur colonne
                                                                            #au lieu d'un vecteur ligne !
        else: #seulement l'ordonnée est en log
            return np.concatenate((res_lin[:,[0]],res_log[:,[1]]),axis=1)

    def getModel(self):

        data=self.getXY()
        if self.model_type=='polynomial':
            params=np.polyfit(x=data[:,0],y=data[:,1],deg=self.polynomial_deg)
        else:
            try:
                params,_= curve_fit(self.model[self.model_type], xdata=data[:,0],ydata=data[0,1])
            except RuntimeError:
                print('Failed to compute a model')
        self.curve_model=(self.model_type,params)
        self.signal_emitter.model_signal.emit(self.QItem)

    def createModelCurve(self):

        model_key,params=self.curve_model
        if model_key=='polynomial':

            def polyN(var,coef):

                func=lambda x:[val*x**(-1*n) for n,val in enumerate(coef,start=-len(coef)+1)]

                return [sum(func(x_val)) for x_val in var]
            x=np.linspace(self.getXY()[0,0],self.getXY()[-1,0],1000)
            return [x.tolist(),polyN(x,params)]

        else:
            #print(self.curve_model)
            return self.model[model_key](self.getXY()[:,0],*params)

class Model():

    def __init__(self):
        toto=0


def main():
    app = QApplication(sys.argv)
    main = MainWindow()
    main.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
