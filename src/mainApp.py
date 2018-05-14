#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import os.path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))
import signal
from misc import getVersion, printDbg
from constants import starting_height, starting_width, user_dir
from PyQt5.Qt import QMainWindow, QIcon, QAction
from mainWindow import MainWindow
from qt.dlg_configureRPCserver import ConfigureRPCserver_dlg

class ServiceExit(Exception):
    """
    Custom exception which is used to trigger the clean exit
    of all running threads and the main program.
    """
    pass
 
 
def service_shutdown(signum, frame):
    print('Caught signal %d' % signum)
    raise ServiceExit



class App(QMainWindow):
 
    def __init__(self, imgDir):
        super().__init__()
        # Register the signal handlers
        signal.signal(signal.SIGTERM, service_shutdown)
        signal.signal(signal.SIGINT, service_shutdown)
        # Get version and title
        self.version = getVersion()
        self.title = 'PET4L - PIVX Emergency Tool For Ledger - v.%s-%s' % (self.version['number'], self.version['tag'])
        # Create the userdir if it doesn't exist
        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
        # Initialize user interface
        self.initUI(imgDir)
        
 
    def initUI(self, imgDir):
        # Set title and geometry
        self.setWindowTitle(self.title)
        self.resize(starting_width, starting_height)
        # Set Icon
        spmtIcon_file = os.path.join(imgDir, 'spmtLogo_shield.png')
        self.spmtIcon = QIcon(spmtIcon_file)
        self.setWindowIcon(self.spmtIcon)
        # Add RPC server menu
        mainMenu = self.menuBar()
        confMenu = mainMenu.addMenu('Setup')
        self.rpcConfMenu = QAction(self.spmtIcon, 'Local RPC Server...', self)
        self.rpcConfMenu.triggered.connect(self.onEditRPCServer)
        confMenu.addAction(self.rpcConfMenu)
        # Create main window
        self.mainWindow = MainWindow(self, imgDir)
        self.setCentralWidget(self.mainWindow)
        # Show
        self.show()
        self.activateWindow()
        
        
        
        
    def closeEvent(self, *args, **kwargs):
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        # Terminate the running threads.
        # Set the shutdown flag on each thread to trigger a clean shutdown of each thread.
        self.mainWindow.myRpcWd.shutdown_flag.set()
        print("Saving stuff & closing...")
        if getattr(self.mainWindow.hwdevice, 'dongle', None) is not None:
            self.mainWindow.hwdevice.dongle.close()
            print("Dongle closed")
        print("Bye Bye.")
        return QMainWindow.closeEvent(self, *args, **kwargs)
    
    
    
    def onEditRPCServer(self):
        # Create Dialog
        try:
            ui = ConfigureRPCserver_dlg(self)
            if ui.exec():
                printDbg("Configuring RPC Server...")
        except Exception as e:
            print(e)
