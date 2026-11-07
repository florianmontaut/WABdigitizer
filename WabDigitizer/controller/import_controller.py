import pandas as pd
import numpy as np
import csv

from PyQt6 import QtGui
from ressources import custom_functions,custom_items,custom_types
from model.Model import Model
from views.View import MainWindow

class ImportController():

    def __init__(self,model:Model,view: MainWindow,**opts):

        self._model = model
        self._view=view
        self._view.loadFile_signal.connect(self.loaderSelect)
        self._model.MAJ_options.connect(self.updateOptions)

        self.file_caracs={'Sampling':1,'Total data points':1,'Trigger time':1,'CH':"",'Data':1}
        self.optsDict={
                        "Remove old viewer data when importing new file"  : "remove_old_graph"  ,
                        "Remove overrange channels"                       : "remove_overrange"  ,
                        "Auto filter"                                     : "auto_filter"       ,
                        "Default sampling for imported generic .csv file" : "default_sampling_txt",
                        "Default sampling for imported .txt file"         : "default_time"
                    }
        self.opts={
                            "remove_old_graph"      : False,
                            "remove_overrange"      : True,
                            "auto_filter"           : False,
                    }
        if opts:
            self.updateOptions(**opts)

    def updateOptions(self,opts=None):

        if opts is None:
            opts=self._model.settings["Import settings"]
        self.opts.update({self.optsDict[key]:item for key,item in opts.items()})

    def openXmlFiles(self,fname):
        """
        Méthode permettant de charger des fichiers .CSV de type GLviewer dans l'appli
        Arguments:
                fnames   --
        Returns:
                None     --
        """

        with open(fname, 'r') as xmlfile:

            #configuration du 'sniffer' csv permettant de déterminer le type de délimiteur ;/,
            dialect = csv.Sniffer().sniff(xmlfile.read(4096), delimiters=';,')
            xmlfile.seek(0)#utilisation du sniffer
            rawtxt = list(csv.reader(xmlfile, dialect))

            #self._model.MAJ_files.emit()
            #Emit réalisé dans le model à la fin de la méthode newFile pour
            #éviter tout problème de synchro

    def openCsvFiles(self,fname):
        """
        Méthode permettant de charger des fichiers .CSV de type GLviewer dans l'appli
        Arguments:
                fnames   --
        Returns:
                None     --
        """

        with open(fname, 'r') as csvfile:

            #configuration du 'sniffer' csv permettant de déterminer le type de délimiteur ;/,
            dialect = csv.Sniffer().sniff(csvfile.read(4096), delimiters=';,')
            csvfile.seek(0)#utilisation du sniffer
            rawtxt = list(csv.reader(csvfile, dialect))

            #self._model.MAJ_files.emit()
            #Emit réalisé dans le model à la fin de la méthode newFile pour
            #éviter tout problème de synchro

    def loadPicture(self,path):
        """
        Méthode permettant de charger une image
        Arguments:
                None   --
        Returns:
                None   --
        """
        #s'il n'existe aucun composant de créé
        if not self._model.components:
            img = QtGui.QImage(QtGui.QPixmap(path))
            self._model.newComponent(IMG=img,component_type=custom_types.componentType.MOSFET)
        else:
            pass


    def loaderSelect(self,loadStruct:tuple[custom_types.fileType,list[str]]):
        """
        Méthode gérant la réception des données du viewer. Cette dernière utilise la méthode
        liée à l'extension du(es) fichier(s) à charger. Seul plusieurs fichiers du même type
        peuvent être chargés par la méthode loaderSelect.

        Arguments:
                fname      --
                fileType   --
        Returns:
                None        --
        """
        load_dict = {custom_types.fileType.XML:self.openXmlFiles,
                    custom_types.fileType.IMG:self.loadPicture,
                    custom_types.fileType.CSV:self.openCsvFiles}

        fileType,fnames=loadStruct

        for fname in fnames:
            load_dict[fileType](fname)
