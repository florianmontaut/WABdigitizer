from PyQt6.QtWidgets import QApplication, QMainWindow,QFontDialog,QDialog,QColorDialog,QGraphicsItem,QLineEdit,QWidget,QFileDialog,QMessageBox,QGridLayout,QDialogButtonBox
from PyQt6.uic import loadUi
from PyQt6 import QtGui,QtCore
import sys  # We need sys so that we can pass argv to QApplication
import pyqtgraph.parametertree as ptree
import pyqtgraph as pg
import json
import numpy as np

class SettingsWindow(QMainWindow):

    def __init__(self,*args,**kwargs):
        params=None
        if 'parameters' in kwargs:
            params=kwargs.pop('parameters')
            
        super(SettingsWindow, self).__init__(*args,**kwargs)

        #Load the UI Page
        loadUi('.\SettingsWindow.ui', self)
        self.populateTree(params)
        self.actionLoad_settings.triggered.connect(self.loadConfig)
        self.actionSave_settings.triggered.connect(self.saveConfig)
        self.actionEdit_settings.triggered.connect(self.editSettings)
        self.config=None
        
        
    def populateTree(self,parameters=None):
        
        if parameters is None :
            parameters = [dict(name='File adress ',type='str',value='toto'),
                        dict(name='Sampling', type='float', value=5.5),
                        dict(name='Total data points',type='int', value=5),
                        dict(name='Creation date',type='str',value=5),
                        dict(name='Start',type='int', limits=[0, 100], value=0),
                        dict(name='Stop',type='int', limits=[0, 100], value=15)] 
        
        self.params = ptree.Parameter.create(name='Files Parameters', type='group', children=parameters)
        self.settingsTree.setParameters(self.params)
    
    #TODO: à faire (le code actuel est un simple copié/collé )
    def loadConfig(self):
        """Méthode permettant de convertir un fichier de config d'un objet CSVStructure vers un dictionnaire exploitable par GLviewer

        Args:
            JSON_file (str): fichier JSON stockant les données d'un enregistrement

        Returns:
            dict: dictionnaire contenant les informations relatives à l'enregistrement (filtrage/modèles/etc...)
        """
        
        fname,_=QFileDialog.getOpenFileName(self,"Load config file","","JSON Files (*.JSON)")
        if not fname:
                return
        
        with open(fname, 'r') as fichier_parametres:
        # Charge le fichier JSON dans une variable config
            config = json.load(fichier_parametres)

        
        def convertToPyKeyWords(rawInput):
        
            KeyWords={"False":False,"false":False,"True":True,"true":True,"None":None,"Null":None,"null":None}
            def recursiveConversion(raw):
                
                out=[]
                for element in raw:
                    
                    newParam={}
                    for key,val in element.items():
                        
                        if key=='children':
                            newParam[key]=list(recursiveConversion(element[key]))
                        elif isinstance(val,str):
                            if val in KeyWords.keys():
                                newParam[key]=KeyWords[val]
                            else:
                                newParam[key]=val
                        else:
                            newParam[key]=val
                        
                    out.append(newParam)
                
                return out
            return recursiveConversion(rawInput)
        
        def convertToDict(input):
            result={}
            for element in input:
                result.update(element.items())
            
            return result
        
        self.config=config
    
    #TODO: à faire (le code actuel est un simple copié/collé )
    def saveConfig(self):
        
        
        if self.GL_files:
            cpt=0
            stack=[]
            with open("sample.json","w") as outfile:
                for file in self.GL_files:
                    
                    stack.append(file.saveToJSONConfig())
                    stack[-1]['type']="GL"
                    print(cpt)
                    
                json_object=json.dumps(stack, indent=2)
                outfile.write(json_object)
    
    def editSettings(self):
        
        
        self.editWindow=OptionsPannel(parameters=self.config)
        #editWindow est un QDialog: la méthode .exec() permet de l'afficher et de récupèrer son "état" lors de sa fermeture
        #actived=1,rejected=0
        if self.editWindow.exec()==1: #si Save est pressé  dans la dialogBox, on récupère les données
            data=self.editWindow.getOptions()
            print(data)


class OptionsPannel(QDialog):
    
    def __init__(self,*args,**kwargs):
        params=None
        if 'parameters' in kwargs:
            params=kwargs.pop('parameters')
        else:
            return -1
        if "UpdateStates" in kwargs:
            newStates=kwargs.pop('UpdateStates')
        else:
            newStates=0
        super(OptionsPannel, self).__init__(*args,**kwargs)

        #Load the UI Page
        loadUi('.\GL_options.ui', self)
        self.tab_dict={}
        self.CreatePannels(params)
        self.buttonBox:QDialogButtonBox
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        
        if newStates is not None:
            self.setOptions(newStates)
        
    def CreatePannels(self,config):
        """Méthode générique permettant de créer n tabulation/panneaux selon le fichier de config

        Args:
            config (list(dict)): liste de dictionnaires où l'on retrouve deux arguments "name" et "params". "name" permet de donner un nom à la tabulation et
                                "params" est un dictionnaire qui sera chargé dans le parameterTree de cette tabulation nouvellement créée.
                                Ex: [dict("name":"toto","params":{"name":"Arg1","type":"bool","value":"True"}),dict(...]
        Returns:
            None
        """
        
        def addPannel(name,data,PannelFrame):
            """Méthode interne gérant la création de la tabulation
            Args:
                data (dict): dictionnaire où l'on retrouve les deux arguments "name" et "params".
                            Ex:dict("name":"toto","params":{"name":"Arg1","type":"bool","value":"True"})
                PannelFrame (QtabWidget): Widget parent dans lequel sera créer la tabulation
            Returns:
                tab  (QtabWidgetItem):  objet tabulation
                params (PyQtgraph.Parameter): groupe des "paramètres" du parametrerTree de la tabulation
            """
            
            tab=QWidget()
            gridLayout = QGridLayout(tab)
            gridLayout.setContentsMargins(5, 5, 5, 5)            
            PannelWidget = ptree.ParameterTree(parent=tab)
            PannelWidget.setIndentation(20)
            PannelWidget.setObjectName("PannelWidget")
            PannelWidget.headerItem().setText(0, "1")
            PannelWidget.header().setVisible(False)
            gridLayout.addWidget(PannelWidget, 0, 0, 1, 1)            
            
            params=ptree.Parameter.create(name='Parameters', type='group',children=data)
            PannelWidget.setParameters(params)            
            PannelFrame.addTab(tab, "")
            PannelFrame.setTabText(PannelFrame.indexOf(tab),name)
            
            return tab,params
        
        #on distingue le chargement via un import JSON (sous forme de liste de dict), d'un chargement direct (sous forme de dictionnaire de dictionnaire)
        if isinstance(config,list):
            for tab in config:
                #on créé un dictinnaire chargé de : "name"=[Widget,params]
                name=tab["name"]
                self.tab_dict[name]=addPannel(name,data=tab["params"],PannelFrame=self.tabWidget)
        else:
            for key,val in config.items():
                self.tab_dict[key]=addPannel(name=key,data=val,PannelFrame=self.tabWidget)
    
    def getOptions(self):
        """Méthode retournant les valeurs des paramètres des différentes tabulations
        Args:
            None
        Returns:
            dict(dict): dictionnaire contenant la valeur des paramètres des différentes tabulations
        """
        
        list_options={}
        
        for key,val in self.tab_dict.items():

            list_options[key]=self.Get_Params_values(val[1])
        
        return list_options
        
    def setOptions(self,config):
        """Méthode affectant les valeurs des paramètres des différentes tabulations

        Args:
            config (list(dict)): liste de dictionnaires où l'on retrouve deux arguments "name" et "params". "name" permet retrouver la tabulation et
                                "params" est un dictionnaire qui sera chargé.
                                Ex: [dict("name":"toto","params":{"name":"Arg1","type":"bool","value":"True"}),dict(...]
                                
                                
        Returns:
            None: 
            
        """
        
        if isinstance(config,list):
            for tab in config:

                self.tab_dict[tab["name"]][1].setParameters(tab["params"])
        elif isinstance(config,dict):            
            for key,val in config.items():
                print(key,val)
                self.tab_dict[key][1].setParameters(val)
        else:
            print("Bad Arg type for OptionsPannel.setOptions method")
            return
    
    
    @staticmethod
    def Get_Params_values(data):
        """
        Méthode permettant d'envoyer les données entrées par l'utilisateur dans le parametrerTree
        Args:
            data (PyQtgraph.Parameter): groupe de "paramètres" du parametrerTree 

        Returns:
            list(dict): dictionnaire contenant les informations relatives à l'enregistrement (filtrage/modèles/etc...)
        
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
                            params_dict[*new_key]=val
                            
                        if data.child(*new_key).hasChildren():
                            
                            recursive_search(new_key)
                else:
                    params_dict[parent_item]=data.child(parent_item).value()
            else:
                
                if data.child(parent_item).hasChildren():
                    for key in data.child(parent_item).keys():
                        
                        if isinstance(parent_item,str):
                            new_key=(parent_item,key)
                        else:
                            new_key=(*parent_item,key)
                        val=data.child(*new_key).value()
                        if val is not None:
                            
                            params_dict[*new_key]=val
                        if data.child(*new_key).hasChildren():
                            
                            recursive_search(new_key)
                else:
                    params_dict[parent_item]=data.child(parent_item).value()
            
            return params_dict
        
        
        #le dictionnaire params_dict ajoute les (keys/values) à chaque recursive_search
        for val in data.keys():
            recursive_search(val)
        return params_dict
    
    
class GraphWindow(QMainWindow):

    def __init__(self,*args,**kwargs):
        
        
        
        if "allowPaste" in kwargs.keys():
            self.allowPaste=kwargs.pop("allowPaste")
        else:
            self.allowPaste=False
        if "grid" in kwargs.keys():
            self.showGrid=kwargs.pop("grid")
        else:
            self.showGrid=False
        super(GraphWindow, self).__init__(*args,**kwargs)

        #Load the UI Page
        loadUi('.\GraphWindow.ui', self)
        #self.df=data
        """
        self.allowPaste=kwargs.get("allowPaste",False)
        self.showGrid=kwargs.get("grid",False)"""
        
        if self.showGrid:
            self.InitGrid()
        self.file_path=None
        self.setAcceptDrops(self.allowPaste)
        
        self.plotgraph=self.maingraph.addPlot(row=0, col=0) #plotgraph est un graphiclayoutwidget, on ajoute un plot maingraph en position 0,0 du layout plotgraph
        self.maingraph.setBackground('w')                   #passage du maingraph en fond blanc
        
        #self.plotgraph.setDownsampling(ds=10,auto=False,mode='peak')#autodownsampling afin de réduire la contrainte d'affichage des courbes thermiques (rapport échantillon/signal excellent)
        #self.plotgraph.setMouseEnabled(x=True, y=False)
        self.legend = pg.LegendItem((80,60), offset=(70,20),colCount=1,verSpacing=-5) 
        self.legend.setParentItem(self.plotgraph.graphicsItem())
        """channels=self.df.columns.tolist()
        n_channels=len(channels)
        colormap=pg.colormap.get('CET-R2')
        colors=colormap.getLookupTable(0,1,n_channels)
        
        try:
                self.plotgraph.multiDataPlot(x=self.df.index.get_level_values(1).tolist(),y=[self.df[channel].to_numpy() for channel in channels],pen=[pg.mkPen(color,width=1) for color in colors],labels=channels)
                for i,curve in enumerate(self.plotgraph.listDataItems()):
                    self.legend.addItem(curve, channels[i])
        except:
                print("échec affichage DF")
                return -1"""
    
    def InitGrid(self):
        
        xp_axis = self.plotgraph.getAxis('bottom')                  
        xticks=[1200,300]
        xp_axis.setTickSpacing(xticks[0],xticks[1])
        ypaxis = self.plotgraph.getAxis('left')
        yticks=[10,2]        
        ypaxis.setTickSpacing(yticks[0],yticks[1])
        self.plotgraph.setLabel('bottom', 'Temps(s)')
        self.plotgraph.setLabel('left', 'Température(°C)')
        self.plotgraph.showGrid(x=True, y=True,alpha=0.3)
        self.plotgraph.setYRange(0,160)
        self.plotgraph.setXRange(0,7200)
    
        
    def keyPressEvent(self, event):
        
        if event.key() == QtCore.Qt.Key.Key_Delete | self.hasFocus() and self.allowPaste:
            
            try:
                Qitem=self.modeltree.selectedItems[0]
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
        else:
            event.ignore()
            
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
        if event.mimeData().hasImage and self.allowPaste:
            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            file_path = event.mimeData().urls()[0].toLocalFile()
            self.set_image(file_path)

            event.accept()
        else:
            event.ignore()
            
    def set_image(self, file_path):

        
        self.file_path=file_path
        self.clearGraph()
        img = QtGui.QImage(QtGui.QPixmap(file_path))
        self.loadGraph(img=img)
    
    def paste_image(self):

        clipboard = QApplication.clipboard()
        mimeData = clipboard.mimeData()
        if mimeData.hasImage():
            img=QtGui.QImage(mimeData.imageData())
            self.loadGraph(img=img)
        else :
            return
    
    
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
        print('toto !')
    
class TextDialog(QDialog):

    def __init__(self,text=None,font=None,color=None,*args,**kwargs):
        QDialog.__init__(self,*args,**kwargs)

        #Load the UI Page
        loadUi('.\TextWindow.ui', self)
        self.fontB.clicked.connect(self.fontChoice)
        self.colorB.clicked.connect(self.fontChoice)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        

        if font is not None:#si font précisé, on le charge (tout cela est nécesaire car le chargement du code html ne semble pas être compatible avec l'éditeur de font : le taille du caractère n'est plus modifiable)
            self.textEdit.setFont(font)
        if color is not None:#si color précisé, on le charge
            self.textEdit.setTextColor(color)
        if text is not None:#si text précisé, on le charge
            self.textEdit.setText(text)
            
    def fontChoice(self):
        font, valid =QFontDialog.getFont()
        if valid:
            self.textEdit.setFont(font)
    
    def fontChoice(self):
        color =QColorDialog.getColor()
        if color.isValid():
            self.textEdit.setTextColor(color)
    
    def getText(self):
        
        return self.textEdit.toHtml(),self.textEdit.font(),self.textEdit.textColor()
    
    #en plus du html qui contient tout les éléments nécessaire, on envoie également le font et la couleur afin de faciliter le renvoie de ces mêmes
    #information au prochaine chargement de la fenêtre

class ScaleDialog(QDialog):

    def __init__(self,Xmin=None,Xmax=None,Ymin=None,Ymax=None,logX=None,logY=None,*args,**kwargs):
        QDialog.__init__(self,*args,**kwargs)

        #Load the UI Page
        loadUi('.\ScaleDialog.ui', self)
        
        
        if Xmin is not None:
            self.XminEdit.setText(str(Xmin))
        if Xmax is not None:
            self.XmaxEdit.setText(str(Xmax))
        if Ymin is not None:
            self.YminEdit.setText(str(Ymin))
        if Ymax is not None: 
            self.YmaxEdit.setText(str(Ymax))
        if logX is not None:
            if logX==True:
                self.XAxisLog.setChecked(True)
        if logY is not None:
            if logY==True:
                self.YAxisLog.setChecked(True)
                
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)
        self.XminEdit.selectAll()#sélection le champ complet XminEdit lors de l'ouverture de la fenêtre ScaleDialog (plus pratique pour réécrire directement la valeur souhaitée)
        

    
    
    
    def getValues(self):
        
        xmin=self.XminEdit.text().replace(',', '.') #remplace le séparateur décimal par un point (compatiblité avec le float, on pourrait modifier la variable global "locale"
        xmax=self.XmaxEdit.text().replace(',', '.')
        ymin=self.YminEdit.text().replace(',', '.')
        ymax=self.YmaxEdit.text().replace(',', '.')
        
        
        return (float(xmin),float(xmax),
                float(ymin),float(ymax),
                self.XAxisLog.isChecked(),self.YAxisLog.isChecked())
    
    #en plus du html qui contient tout les éléments nécessaire, on envoie également le font et la couleur afin de faciliter le renvoie de ces mêmes
    #information au prochaine chargement de la fenêtre



class pgText(pg.TextItem):
    def __init__(self,text=None,*args,**kwargs):        
        pg.TextItem.__init__(self,text,*args,**kwargs)
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable|QGraphicsItem.GraphicsItemFlag.ItemIsMovable) #ItemIsMovable remplace la fonction MouseDragEvent
        self.text=text
        self.Onflag=False #flag ne permettant l'ouverture que d'une seule fenêtre par pgTextitem en même temps
        self.font=None
        self.setZValue(1)


    def keyPressEvent(self, event):
        
        if event.key() == QtCore.Qt.Key.Key_Delete | self.hasFocus():
            #//TODO : l'élément est caché pour l'instant (il devrait être détruit mais je ne sais l'implémenter)
            self.hide()
        event.accept()

    
    def mousePressEvent(self,ev):
        if ev.button() != QtCore.Qt.MouseButton.LeftButton :
            ev.ignore()
            return

        ev.accept()
        
    def mouseDoubleClickEvent(self,ev):
        if self.Onflag==True: #si fenêtre déjà ouverte on sort de la fonction
            return 
        else:
            self.Onflag=True #mise à 1 du flag éditeur ouvert
            self.textEditor()
            
        self.Onflag=False #on est sorti de l'éditeur, mise à 0 du flag
        ev.accept()
        
    """ #Ce bout de code n'est plus nécessaire mais il demontre le principe de déplacement X/Y par maintient clic gauche +souris 
    def mouseDragEvent(self, ev):
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            ev.ignore()
            return

        if ev.isStart():
            self.dragOffset=self.pos()-ev.buttonDownScenePos()
        elif ev.isFinish():
            
            return
        
        self.setPos(ev.scenePos()+self.dragOffset)
        ev.accept()
    """
    
    def textEditor(self):
        
        if self.toPlainText()!=None:
            self.window=TextDialog(text=self.toPlainText(),font=self.font,color=self.color)
        else:
            self.window=TextDialog()
            
        self.window.show()
        if self.window.exec()==QMessageBox.StandardButton.Ok: #si OK est pressé  dans la dialogBox, on récupère les données
                html,self.font,self.color=self.window.getText()
                self.setHtml(html)



def main():
    app = QApplication(sys.argv)
    
    
    main = GraphWindow()
    main.show()
    
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
    
    
    		
