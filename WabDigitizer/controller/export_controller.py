PATH='./WabDigitizer/ressources'

import xml.sax



class ExportController:

    def __init__(self,model,view):

        self._model=model
        self._view=view


class componentHandler(xml.sax.ContentHandler):

    def startElement(self, name, attrs):
        self.current=name

            #print(attrs['class'])
            #permet d'accéder aux attributs des Elements :
            #Exmample <Package class="Diode" vendor="ST" partnumber="STTH60RQ06">
            #class, vendor et partnumber sont des attributs (attrs)

    def endElement(self, name):
        if name =='TurnOnLoss':
            print(f'{self.Eon}')


    def characters(self,content):
        if self.current == 'TurnOnLoss':
            self.Eon=content
        if self.current == 'TurnOffLoss':
            self.Eoff=content
        if self.current == 'ConductionLoss':
            self.conduct=content
        if self.current == 'ThermalModel':
            self.thermal=content





def main():

    handler=componentHandler()
    parser = xml.sax.make_parser()
    parser.setContentHandler(handler)
    parser.parse(PATH+'/PMF75-120-S002_Mosfet.xml')



if __name__=='__main__':
    
    from lxml import objectify
    from xmlschema import XMLSchema, etree_tostring

    import lxml.etree as ET
    from dataclasses import dataclass

    tree = ET.parse(PATH+'/PMF75-120-S002_Mosfet.xml')
    root= tree.getroot()


    xml_dict=[]
    for child in root:
        key=child.tag
        key=key[key.rfind('}')+1:]
        key
        ''
        print(key)
