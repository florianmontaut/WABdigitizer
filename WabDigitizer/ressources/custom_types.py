from enum import Enum,auto
from syslog import LOG_FTP

class itemType(Enum):

    FILE=auto()
    GRAPH=auto()
    RAW=auto()
    MODEL=auto()
    COMPONENT=auto()
    PARAM=auto()
    CURVE=auto()

class componentType(Enum):

    MOSFET=auto()
    DIODE=auto()
    IGBT=auto()
    CUSTOM=auto()

class axisScale(Enum):

    LINEAR = auto()
    LOG = auto()
    LOG_LINEAR = auto()
    LINEAR_LOG = auto()


class qSignalType(Enum):

    LOAD=auto()     #Event demande chargement d'un fichier
    MODEL=auto()    #Event demande création d'un modèle
    SCALE=auto()    #Event changement d'échelle
    DEL=auto()      #Event demande de supression d'un élément
    SELECT=auto()   #Event sélection
    ADD=auto()  #Event activation du menu des options
    OPTIONS=auto()  #Event activation du menu des options

class fileType(Enum):

    IMG=auto()
    XML=auto()
    CSV=auto()

class modelType(Enum):

    POLY=auto()
    EXP=auto()
    FIRST_ORDER=auto()
    SECOND_ORDER=auto()

class degree(Enum):

    FARENHEIT=auto()
    CELSIUS=auto()


class CharacteristicType(Enum):

    OUTPUT_CHARACTERISTIC   = auto()
    TRANSFER_CHARACTERISTIC = auto()
    RDS_ON                  = auto()
    CISS                    = auto()
    COSS                    = auto()
    CRSS                    = auto()
    QG                      = auto()    
    QGD                     = auto()    
    QGS                     = auto()    
    EON                     = auto()    
    EOFF                    = auto()        
    ERR                     = auto()    
    VF                      = auto()    
    ZTH                     = auto()
    L_m                     = auto()
    L_f                     = auto()    

