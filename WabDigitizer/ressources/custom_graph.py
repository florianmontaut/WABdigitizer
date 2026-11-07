from PyQt6 import QtCore
import pyqtgraph as pg

import numpy as np


class Graph(pg.GraphItem):

    def __init__(self,init_x,init_y):
        self.origin_x=init_x
        self.origin_y=init_y
        self.dragPoint = None
        self.dragOffset_x = None
        self.dragOffset_y = None
        pg.GraphItem.__init__(self)
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

        #on trie les points par X croissant : permet de rajouter un point dans la courbe
        #sans faire revenir la courbe en arrière cette opération se fait uniquement lors de
        #l'ajout d'un point. L'essai de la maj après un évènement de drag&drop provoque le
        #déplacement des points intervertis après le tri selon les X
        #(il faudrait mettre à jour l'indice du point sélectionné en fonction de son abscisse)

        if 'pos' in kwds:
            pos=kwds['pos']
            kwds['pos']=pos[pos[:,0].argsort()]
            #les points sont triés par abscisse croissante

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