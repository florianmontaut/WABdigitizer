import pandas as pd
import datetime
import csv
import numpy as np

from PyQt6 import QtCore,QtGui
from PyQt6.QtWidgets import QFileDialog,QTreeWidgetItem

import pyqtgraph as pg
import pyqtgraph.parametertree as ptree

from ressources import custom_functions, custom_types,custom_items
from model.Model import Model,Component,Parameter,DigitizedCurve
from views.View import MainWindow
from controller.tree_controller import TreeController
from controller.graph_controller import GraphController
from controller.parameter_controller import ParameterController
from controller.workspace_controller import WorkspaceController
from controller.import_controller import ImportController
from controller.export_controller import ExportController
from controller.menu_controller import MenuController
from controller.cursor_controller import CursorController


class MainController(QtCore.QObject):

    def __init__(self, view : MainWindow, params = dict):



        super().__init__()
        self.view = view
        self.settings={} #? basculer settings dans model ? (PipelineTreeModel) 16/03

        # Contrôleurs UI
        self.tree_ctrl      = TreeController(view.treefile)
        # Menu_ctrl en deuxième position afin de récupérer les options utilisateur puis les
        # transmettre aux autres contrôleur
        self.menu_ctrl      = MenuController(view, params, 'Digitizer_test')
        self.graph_ctrl     = GraphController(view.maingraph,view.graphTree)
        plotItem=[item for item in view.maingraph.items() if isinstance(item,pg.PlotItem)][0]
        self.param_ctrl     = ParameterController(view.selectiontree,plotItem)

        self.cursor_ctrl    = CursorController()

        # Contrôleurs fonctionnels
        self.import_ctrl = ImportController(view)
        self.export_ctrl = ExportController(view)

        # Le modèle Qt sera instancié après chargement de fichier
        self.workspace_ctrl = None
        self.model = None
        self.workspace = Workspace()
        self.settings = self.menu_ctrl.params
        self.on_snap_toggled(True)

        # Connexions globales GUI
        self._connect_UI_actions()
        self._connect_tree_signals()
        self._connect_graph_signals()
        self._connect_param_signals()
        self._connect_import_signals()
        self._connect_menu_signals()
        self._connect_cursor_signals()



    # -------------------------------------------------------------------------
    # MENU FILE
    # -------------------------------------------------------------------------
    def _connect_UI_actions(self):
        """
        Connecte les actions de la barre de menu à des slots du MainController.
        """

        self.view.actiongraph.triggered.connect(lambda: self.import_ctrl.load_file_dialog(
                                                    custom_types.fileType.GL))
        self.view.actionmodel.triggered.connect(lambda: self.import_ctrl.load_file_dialog(
                                                    custom_types.fileType.JSON))
        self.view.actionParameters.triggered.connect( self.menu_ctrl.open_options_window)
        self.view.actionSave_model.triggered.connect(lambda: self.export_ctrl.save_workspace(
                                                                    self.workspace))
        self.view.actionQuit.triggered.connect(self.quit)




    def _init_undo_redo(self):
        """
        Initialise les actions Undo/Redo liées à la pile d'actions du WorkspaceController.
        """
        self.undo_action = self.workspace_ctrl.undo_stack.createUndoAction(self.view, "Undo")
        self.redo_action = self.workspace_ctrl.undo_stack.createRedoAction(self.view, "Redo")
        self.undo_action.setShortcut(QtGui.QKeySequence.StandardKey.Undo)
        self.undo_action.setShortcutContext(QtCore.Qt.ShortcutContext.WindowShortcut)

        self.redo_action.setShortcut(QtGui.QKeySequence.StandardKey.Redo)
        self.redo_action.setShortcutContext(QtCore.Qt.ShortcutContext.WindowShortcut)

        self.view.addAction(self.undo_action)
        self.view.addAction(self.redo_action)



    # -------------------------------------------------------------------------
    # Menu Bar signals
    # -------------------------------------------------------------------------
    def _connect_menu_signals(self):
        """
        Connecte les signaux émis par le MenuController à des slots du MainController.
        """
        #? Envoi direct à un autre controller sans vérification du main_controller ?
        self.menu_ctrl.loadSignal.connect(self.import_ctrl.loaderSelect)
        self.menu_ctrl.newOptions.connect(self._on_new_settings)
        
    def _on_new_settings(self, settings: dict):
        """
        Slot appelé lorsque l'utilisateur modifie les options dans le MenuController.
        """
        self.settings = settings
        self.import_ctrl.updateOptions(settings)
        self.graph_ctrl.updateOptions(settings)
        
        
        
        
        #TODO#: vieux code
        self._model=model
        self._view=view
        self._view.UIsignals.connect(self.filterUIsignals)
        self._view.componentTree.itemClicked.connect(self.updateSelectionTree)
        self._model.MAJ_options.connect(self.updateOptions)
        self.old_selection=None
        self.currentGraphAdress=None

        self.optsDict={
                        "Cut-off frequency"  : "filter_freq"
                        }
        self.opts={
                    "filter_freq":    0.003
                    }

        if opts:
            self.updateOptions(**opts)

    def updateOptions(self,opts=None):

        if opts is None:
            opts=self._model.settings["Filter settings"]
        self.opts.update({self.optsDict[key]:item for key,item in opts.items()})

    def updateSelectionTree(self,item:QTreeWidgetItem,curve:pg.PlotItem = None):
        """Méthode mettant à jour l'arborescence des options de modifications des signaux
        Args:
            item (QTreeWidgetItem): item sélectionné par l'utilisateur. Si c'est un signal,
                                    la méthode met à disposition les méthodes de filtrage et
                                    de modification du graph. Si c'est un fichier racine, elle
                                    retourne les méthodes de décalage et troncage des données
        """
        #Zoom sur la sélection
        self._view.componentTree.scrollTo(self._view.componentTree.indexFromItem(item))

        if item is self.old_selection:
            return
        else:
            self.old_selection=item
            if item.type==custom_items.itemType.PARAM :
                self.currentGraphAdress=item.struct.adress

        if item.type==custom_items.itemType.COMPONENT:
            self._view.highlight(item,None)
            params=item.ItemParameters()
            self._view.selectionTree.setParameters(params)
            def update_component():
                #treeItem update
                item.saveParam()
                #model update
                self._model.getItemData(absolute_id=item.absoluteId).struct=item.struct

            params.blockSignals(True)
            params.sigTreeStateChanged.connect(update_component)
            params.param('Add parameter').sigActivated.connect(lambda : self.newParameter(parent=item))
            params.blockSignals(False)

        elif item.type==custom_items.itemType.PARAM:

            params=item.ItemParameters()
            self._view.selectionTree.setParameters(params)
            if item.struct.adress is not None:
                self._view.clearGraph()
                self._view.loadGraph(item)
                self._view.setGridScale(item)

            def update_param():
                #update du treeItem
                item.saveParam()
                #update du model
                self._model.getItemData(absolute_id=item.absoluteId).struct=item.struct

            params.blockSignals(True)
            params.sigTreeStateChanged.connect(update_param)
            params.param('Add curve').sigActivated.connect(lambda : self.newCurve(parent=item))
            params.blockSignals(False)

        elif item.type==custom_items.itemType.CURVE:

            if item.parent().struct.adress is not self.currentGraphAdress:
                self._view.clearGraph()
                self._view.loadGraph(item.parent())
                self._view.setGridScale(item.parent())

            if item.curve is not None :
                self._view.highlight(item,item.curve)
                def update_plot():
                    #! load gragh parent et sélectionne la courbe si elle existe
                    self._view.updateGraphColor(item.curve)

            params=item.ItemParameters()
            self._view.selectionTree.setParameters(params)
            params.sigTreeStateChanged.connect(update_plot)

            def update_pen():
                pen = params.child('Curve pen').value()
                item.curve.setPen(pen)
                custom_functions.setItemFont(item,brush = pg.mkBrush(pen.color()))
            def model_curve():
                pass
                #selected_model = modelizer.getFunction()
                #self.getThermalModel(items = [item], model = selected_model)
            params.sigTreeStateChanged.connect(update_pen)
            #modelizer.createModel.sigActivated.connect(model_curve)


    def removeSignal(self,it = None):
        if it :
            table_qitems = [it]
        else:
            table_qitems = custom_functions.getItems(self.componentTree,type_methode = 'selected')
        if table_qitems is not None:
            root = self.componentTree.invisibleRootItem()
            for item in table_qitems:
                #print(item)
                if item.flags()& QtCore.Qt.ItemFlag.ItemIsAutoTristate:
                    (item.parent() or root).removeChild(item)
                else:
                    item.setDisabled(True)
                    item.setCheckState(0,QtCore.Qt.CheckState.Unchecked)
                    item.setFlags(item.flags()& ~QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                    if self._model.curves :
                        try:
                            curve = [curve for curve,tree_item in self._model.curves if
                                    tree_item==item][0]
                            if curve in self._view.plotgraph.listDataItems():
                                self._view.plotgraph.removeItem(curve)
                        except:
                            pass

    def filterUIsignals(self,signal_struct):

        signal_type,args=signal_struct
        if signal_type==custom_types.qSignalType.SCALE:
            self.getThermalModel(args)
        elif signal_type==custom_types.qSignalType.MODEL:
            self.getThermalModel(args)
        elif signal_type==custom_types.qSignalType.LOAD:
            pass
        elif signal_type==custom_types.qSignalType.SELECT:
            self.updateSelectionTree(args[0])
        elif signal_type==custom_types.qSignalType.OPTIONS:
            self._model.changeSettings(args)


    def remove(self,table_qitems):

        root = self._view.componentTree.invisibleRootItem()
        for item in table_qitems:
            if item.flags()& QtCore.Qt.ItemFlag.ItemIsAutoTristate:
                (item.parent() or root).removeChild(item)
            else:
                item.setDisabled(True)
                item.setCheckState(0,QtCore.Qt.CheckState.Unchecked)
                item.setFlags(item.flags()& ~QtCore.Qt.ItemFlag.ItemIsUserCheckable)
                if self._model.curves :
                    try:
                        curve = [curve for curve,tree_item in self._model.curves if
                                tree_item==item][0]
                        if curve in self._view.plotgraph.listDataItems():
                            self._view.plotgraph.removeItem(curve)
                    except:
                        pass

    def newParameter(self,parent):

        self._model.addParameter(item=parent,cpt=self._model.cpt_id)
        self._model.cpt_id+=1
        self._model.MAJ_component.emit(parent)

    def newCurve(self,parent):
        self._model.addCurve(item=parent,cpt=self._model.cpt_id)
        self._model.cpt_id+=1
        self._model.MAJ_component.emit(parent)
