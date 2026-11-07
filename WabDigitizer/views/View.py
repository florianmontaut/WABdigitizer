import numpy as np

from PyQt6.QtWidgets import QMenu,QTreeWidgetItem,QTreeWidgetItemIterator,QApplication,QMenu
from PyQt6 import QtGui,QtCore

import pyqtgraph as pg

from ressources import custom_functions,custom_types,custom_items
from views import WabWindows
from views import WabDialogs
from model.Model import Model
PATH='./WabDigitizer/views/'


class MainWindow(WabWindows.WabWindow):
    """
    Viewer du WabDigitizer

    Classe parent:
        QMainWindow (GLWindows.GLWindow): classe ou superclasse contenant les méthodes
                                        générique du viewer (initialisation,options,etc...)
    """

    def __init__(self,model:Model,params,**opts):

        super(MainWindow, self).__init__(params,**opts)
        self._model : Model = model
        self.sessions_opts={}
        #!self.mouseCursor=self.graphTree_params.param('Graphics items','Mouse cursor')

        self.actionParameters.triggered.connect(self.openOptionsWindow)
        self._model.MAJ_component.connect(self.loadTree)
        #!self._model.MAJ_signal.connect(self.loadSignal)
        #self.componentTree.itemChanged.connect(self.onItemChecked)
        self._model.MAJ_options.connect(self.updateOptions)

        #*loadFile_signal(voir GLWindows) a pour slot ImportController.loaderSelect
        #*UIsignals (voir GLWindows) a pour slot MainController.filterUIsignals

    def onItemChecked(self,item,col):

        if col!=0 or item.type is custom_types.itemType.FILE:
            return
        else:
            if item.state is QtCore.Qt.CheckState.Unchecked:
                if item.curve in self.plotgraph.listDataItems():
                    self.plotgraph.removeItem(item.curve)
            elif item.state is QtCore.Qt.CheckState.Checked and not item.isDisabled():
                if item.curve not in self.plotgraph.listDataItems():
                    self.plotgraph.addItem(item.curve)
                    #self.updateGraphBounds()
            if self.opts["update_selected"]:
                self.vb.autoRange()

    def openOptionsWindow(self):
        """
        Méthode gérant l'éxécution de la fenêtre de dialogue regroupant
        les options du GLViewer
        """

        OptionsWindow = WabDialogs.OptionsPannel(parameters = self.option_params,
                                            UpdateStates = self._model.settings)
        OptionsWindow.accepted.connect(lambda: self.UIsignals.emit(
                                            (custom_types.qSignalType.OPTIONS,
                                                    OptionsWindow.getOptions())))
        OptionsWindow.show()

    def updateOptions(self,opts=None):

        if opts is None:
            opts=self._model.settings["Graph settings"]

        self.opts.update({self.optsDict[key]:item for key,item in opts.items()})
        self.plotgraph: pg.PlotItem
        if self.opts["downsample"]:
            self.plotgraph.setDownsampling(mode=self.opts["downsample_type"],
                                            ds=self.opts["downsample_ratio"])
        xp_axis = self.plotgraph.getAxis('bottom')
        xp_axis.setLabel(text=self.opts["X_title"],units=self.opts["X_unit"])
        yp_axis = self.plotgraph.getAxis('left')
        yp_axis.setLabel(text=self.opts["Y_title"],units=self.opts["Y_unit"])


    def removeItems(self,it = None):
        if it :
            table_qitems = [it]
        else:
            table_qitems = custom_functions.getItems(self.componentTree,type_methode = 'selected')
        if table_qitems is not None:
            self.UIsignals.emit([custom_types.qSignalType.DEL,table_qitems])

    def export(self):
        # Handle the "Action 1" action

        item = custom_functions.getItems(self.componentTree,type_methode = 'selected') [0]
        file_id,signal_id=item.file_id
        if item.params.child('Curve modeling','Use vertical cursors as limits').value():
            limits=self.graphTree_params.child('Graphics items','Vertical cursors').getData()[0:2]
            if limits is not None:
                limits=limits.reverse() if limits[1]-limits[0]<0 else limits
        else:
            limits=None
        data=self._model.components[file_id].getXYFromDataFrame(name=item.name,custom_limit=limits)
        """listCoef=[np.format_float_scientific(val, unique=False, precision=3)
                    for val in data]

        coefStr=''.join(['\t'.join(listCoef)])"""
        data=list(zip(data[0],data[1]))
        data=[str(val[0])+'\t'+str(val[1]) for val in data]
        exportData=''.join(['\n'.join(data)])
        QApplication.clipboard().setText(exportData)

    def actionsConcentrator(self,key:custom_types.qSignalType)->None:
        """
        Méthode servant d'interface entre l'arborescence des fichiers GL et les méthodes
        de traitements des signaux comme 'filtrer', 'deltaT', etc..
        Args:
            key (str):  key permettant de sélectionner la méthode à appliquer
        """
        table_qitems = custom_functions.getItems(self.componentTree,type_methode = 'selected')
        if key is custom_types.qSignalType.MODEL:
            self.UIsignals.emit((custom_types.qSignalType.MODEL,(table_qitems)))

    def loadTree(self,item):

        #supression de l'affichage actuel
        self.componentTree.invisibleRootItem().takeChildren()

        if item.type is custom_types.itemType.COMPONENT :
            self.componentTree.invisibleRootItem().addChild(item)
            item.setExpanded(True)
            #item.checkItem(True)
        else:
            self._model.qitems_dict[item.parentId].addItem(item)
            #item.checkItem(True)

        self.componentTree.resizeColumnToContents(0)
        self.componentTree.resizeColumnToContents(1)

    def loadSignal(self,parent,item):

        parent.addItem(item)
        item.checkItem(True)
        self.componentTree.resizeColumnToContents(0)
        self.componentTree.resizeColumnToContents(1)
        if item.state is QtCore.Qt.CheckState.Checked and item.type is not custom_types.itemType.FILE:
                self.traceItem(item)


    def updateTableXY(self):
        def update_points():
            """
            Fonction interne ajoutant les coordonnées XY dans la table d'affichage à
            chaque fois qu'un point est ajouté
            Arguments:
                    None  --
            Returns:
                    None  --

            Lorsque l'on modifie les points via le tableau il faut alors
            bloquer le signal de MAJ du graph sans quoi on rentre dans une boucle infinie
            """
            #self.tableXY.blockSignals(True)
            self._view.selected_curve.graph.scatter.blockSignals(True)
            points=self.selected_curve.setXY(np.row_stack([(float(self.tableXY.item(row,0).text()),
                                                            float(self.tableXY.item(row,1).text()))
                                                            for row in range(self.tableXY.rowCount())]))
            self._view.selected_curve.graph.setCurve(pos=points)
            self._view.selected_curve.graph.scatter.blockSignals(False)

        pos=self.selected_curve.graph.data['pos']
        self._view.tableXY.blockSignals(True)
        #self.selected_curve.graph.scatter.blockSignals(True)
        self._view.tableXY.setData(self.selected_curve.getXY())
        self._view.tableXY.blockSignals(False)
        #self.selected_curve.graph.scatter.blockSignals(False)
        self._view.tableXY.cellChanged.connect(update_points)

    def updateGraphColor(self,curve):

        curve.setCurve(pen=self.curve_color,symbol=self.symbol_shape,symbolBrush=self.symbol_color,size=self.symbol_size)

    def setPos(self,val,paramItem:custom_items.parameterTreeItem):
        """
        Méthode permettant de convertir les valeurs du tableau en QPoint utilisable
        par le plotWidget. Example: P1 (5V;85A) devient Qpoint((203,589))

        Args:
            val (list(tuple(float))) : liste des valeurs du tableau [(x0,y0),(x1,y1)...]
            paramItem (custom_items.parameterTreeItem): échelle de l'image/graph

        Returns:
            pos (list(tuple(float))) : liste des coordonnées des points de la courbe
        """
        scale=paramItem.struct.coordinate

        if scale.xlog==False and scale.ylog==False: #échelles linéaires
            return paramItem.offset_grid+(val-paramItem.offset_scale)/paramItem.delta

        res_log=paramItem.offset_grid+(np.log10(val)-paramItem.offset_scale)/paramItem.delta

        #échelles logs
        if scale.xlog==True and scale.ylog==True:
            return res_log

        res_lin=paramItem.offset_grid+(val-paramItem.offset_scale)/paramItem.delta

        #si xlog vrai alors l'abscisse est en log sinon c'est les ordonnées
        if scale.xlog==True:
            return np.concatenate((res_log[:,[0]],res_lin[:,[1]]),axis=1)
        else:
            return np.concatenate((res_lin[:,[0]],res_log[:,[1]]),axis=1)

    def getVal(self,pos,paramItem:custom_items.parameterTreeItem):
        """
        Méthode permettant de convertir les QPoints du plotWidget en grandeur physique
        Example: Qpoint((203,589)) devient P1 (5V;85A)

        Args:
            pos (list(tuple(float))) : liste des coordonnées des points de la courbe
            paramItem (custom_items.parameterTreeItem): échelle de l'image/graph

        Returns:
            val (list(tuple(float))) : liste des coordonnées des points de la courbe
        """
        scale=paramItem.struct.coordinate

        if scale.xlog==False and scale.ylog==False: #échelles linéaires
            return (pos-paramItem.offset_grid)*paramItem.delta+paramItem.offset_scale

        res_log=np.power(10,(pos-paramItem.offset_grid)*paramItem.delta+paramItem.offset_scale)
        #échelles logs
        if scale.xlog==True and scale.ylog==True:
            return res_log

        res_lin=(pos-paramItem.offset_grid)*paramItem.delta+paramItem.offset_scale

        #si xlog vrai alors l'abscisse est en log sinon c'est les ordonnées
        if scale.xlog==True:
            return np.concatenate((res_log[:,[0]],res_lin[:,[1]]),axis=1)
        else:
            return np.concatenate((res_lin[:,[0]],res_log[:,[1]]),axis=1)