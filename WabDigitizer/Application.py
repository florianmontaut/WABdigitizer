import sys
from PyQt6.QtWidgets import QApplication

from views.View import MainWindow
from model.Model import Model
from controllers import main_controller,import_controller
from WabDigitizer.ressources import custom_viewer_settings
import qdarktheme

#**********************************************************************************************************#
#   GLviewer est une application permettant de rapidement et facilement observer, modifier, sauvegarder    #
#   des fichiers de points .txt, .csv notamment provennant des dataloggers GraphTec.                       #
#   Une architecture Model View Controller a été choisi pour le développement de ce programme.             #
#   Afin de privilégier les perfomances (MouseMoved particulièrement), le viewer accède directement au     #
#   model (semble être contraire au principe du MVC mais je n'ai pas vu de réponse claire sur le sujet)    #
#**********************************************************************************************************#

class App(QApplication):

    def __init__(self,sys_argv):
        super(App,self).__init__(sys_argv)
        qdarktheme.setup_theme("auto")
        application_params = custom_viewer_settings.params

        #! params sera un fichier .ini ou un projet sauvegardant les dernières modifications enregistrées
        #! dans le GLviewer
        #! les params sont transmis à la création des objets et MAJ via signal

        self.model = Model() #! Model(session_params['Model'])
        self.main_view = MainWindow(self.model,application_params)
        self.main_controller = main_controller.MainController(self.model,self.main_view)
        self.import_contoller = import_controller.ImportController(self.model,self.main_view)
        self.main_view.show()





    def toggle_theme(self,opts) -> None:
        dark=opts.get('dark_mode',False)

        if dark :
            palette     = qdarktheme.load_palette(theme="dark")
            stylesheet  = qdarktheme.load_stylesheet(theme="dark")
        else:
            palette     = qdarktheme.load_palette(theme="auto")
            stylesheet  = qdarktheme.load_stylesheet(theme="auto")

        self.setPalette(palette)
        self.setStyleSheet(stylesheet)

        # vérification de l'adresses mémoire du model : les trois doivent pointer à la même adresse
        # print(self.model,self.main_controller._model,self.main_view._model)

if __name__ == '__main__':
    app = App(sys.argv)
    sys.exit(app.exec())
