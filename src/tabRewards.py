#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import threading
import simplejson as json

from PyQt5.Qt import QApplication, pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QMessageBox, QTableWidgetItem, QHeaderView

from constants import MINIMUM_FEE
from misc import printDbg, printError, printException, getCallerName, getFunctionName, \
    persistCacheSetting, myPopUp, myPopUp_sb, DisconnectedException
from pivx_parser import ParseTx
from qt.gui_tabRewards import TabRewards_gui
from threads import ThreadFuns
from utils import checkPivxAddr


class TabRewards():
    def __init__(self, caller):
        self.caller = caller
        ##--- Lock for loading UTXO thread
        self.runInThread = ThreadFuns.runInThread
        self.Lock = threading.Lock()

        ##--- Initialize Selection
        self.utxoLoaded = False
        self.selectedRewards = None
        self.feePerKb = MINIMUM_FEE
        self.suggestedFee = MINIMUM_FEE

        ##--- Initialize GUI
        self.ui = TabRewards_gui(self.caller.imgDir)
        self.caller.tabRewards = self.ui

        # load last used destination from cache
        self.ui.destinationLine.setText(self.caller.parent.cache.get("lastAddress"))
        # load useSwiftX check from cache
        if self.caller.parent.cache.get("useSwiftX"):
            self.ui.swiftxCheck.setChecked(True)

        self.updateFee()

        # Connect GUI buttons
        self.ui.addySelect.currentIndexChanged.connect(lambda: self.onChangeSelected())
        self.ui.rewardsList.box.itemClicked.connect(lambda: self.updateSelection())
        self.ui.btn_reload.clicked.connect(lambda: self.loadSelection())
        self.ui.btn_selectAllRewards.clicked.connect(lambda: self.onSelectAllRewards())
        self.ui.btn_deselectAllRewards.clicked.connect(lambda: self.onDeselectAllRewards())
        self.ui.swiftxCheck.clicked.connect(lambda: self.updateFee())
        self.ui.btn_sendRewards.clicked.connect(lambda: self.onSendRewards())
        self.ui.btn_Cancel.clicked.connect(lambda: self.onCancel())

        # Connect Signals
        self.caller.sig_UTXOsLoading.connect(self.update_loading_utxos)
        self.caller.sig_UTXOsLoaded.connect(self.display_utxos)



    def display_utxos(self):
        # update fee
        if self.caller.rpcConnected:
            self.feePerKb = self.caller.rpcClient.getFeePerKb()
            if self.feePerKb is None:
                self.feePerKb = MINIMUM_FEE
        else:
            self.feePerKb = MINIMUM_FEE

        rewards = self.caller.parent.db.getRewardsList(self.curr_addr)

        if rewards is not None:
            def item(value):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                return item

            # Clear up old list
            self.ui.rewardsList.box.setRowCount(0)
            # Make room for new list
            self.ui.rewardsList.box.setRowCount(len(rewards))
            # Insert items
            for row, utxo in enumerate(rewards):
                txId = utxo.get('txid', None)
                pivxAmount = round(int(utxo.get('satoshis', 0)) / 1e8, 8)
                self.ui.rewardsList.box.setItem(row, 0, item(str(pivxAmount)))
                self.ui.rewardsList.box.setItem(row, 1, item(str(utxo.get('confirmations', None))))
                self.ui.rewardsList.box.setItem(row, 2, item(txId))
                self.ui.rewardsList.box.setItem(row, 3, item(str(utxo.get('vout', None))))
                self.ui.rewardsList.box.showRow(row)

            self.ui.rewardsList.box.resizeColumnsToContents()

            if len(rewards) > 0:
                self.ui.rewardsList.statusLabel.setVisible(False)
                self.ui.rewardsList.box.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

            else:
                if not self.caller.rpcConnected:
                    self.ui.resetStatusLabel('<b style="color:red">PIVX wallet not connected</b>')
                else:
                    self.ui.resetStatusLabel('<b style="color:red">Found no Rewards for %s</b>' % self.curr_addr)



    def getSelection(self):
        # Get selected rows indexes
        items = self.ui.rewardsList.box.selectedItems()
        rows = set()
        for i in range(0, len(items)):
            row = items[i].row()
            rows.add(row)
        indexes = list(rows)
        # Get UTXO info from DB for each
        selection = []
        for idx in indexes:
            txid = self.ui.rewardsList.box.item(idx, 2).text()
            txidn = int(self.ui.rewardsList.box.item(idx, 3).text())
            selection.append(self.caller.parent.db.getReward(txid, txidn))

        return selection



    def loadSelection(self):
        # Check dongle
        printDbg("Checking HW device")
        if self.caller.hwStatus != 2:
            myPopUp_sb(self.caller, "crit", 'PET4L - hw device check', "Connect to HW device first")
            printDbg("Unable to connect - hw status: %d" % self.caller.hwStatus)
            return None

        self.ui.addySelect.clear()
        ThreadFuns.runInThread(self.loadSelection_thread, ())



    def loadSelection_thread(self, ctrl):
        hwAcc = self.ui.edt_hwAccount.value()
        spathFrom = self.ui.edt_spathFrom.value()
        spathTo = self.ui.edt_spathTo.value()
        intExt = self.ui.edt_internalExternal.value()
        isTestnet = self.caller.isTestnetRPC

        for i in range(spathFrom, spathTo+1):
            path = "%d'/%d/%d" % (hwAcc, intExt, i)
            address = self.caller.hwdevice.scanForAddress(hwAcc, i, intExt, isTestnet)
            try:
                balance = self.caller.apiClient.getBalance(address)
            except Exception as e:
                print(e)
                balance = 0

            itemLine = "%s  --  %s" % (path, address)
            if(balance):
                itemLine += "   [%s PIV]" % str(balance)

            self.ui.addySelect.addItem(itemLine, [path, address, balance])



    def load_utxos_thread(self, ctrl):
        with self.Lock:
            # clear utxos DB
            printDbg("Updating UTXOs...")
            self.caller.parent.db.clearTable('UTXOS')
            self.utxoLoaded = False

            if not self.caller.rpcConnected:
                printError(getCallerName(), getFunctionName(), 'PIVX daemon not connected - Unable to update UTXO list')
                return

            utxos = self.caller.apiClient.getAddressUtxos(self.curr_addr)
            total_num_of_utxos = len(utxos)

            # Get raw transactions
            curr_utxo = 0
            percent = 0
            for u in utxos:
                rawtx = None
                percent = int(100 * curr_utxo / total_num_of_utxos)
                rawtx = self.caller.rpcClient.getRawTransaction(u['txid'])

                # break if raw TX is unavailable
                if rawtx is None:
                    return

                # Save utxo to db
                u['receiver'] = self.curr_addr
                u['raw_tx'] = rawtx
                self.caller.parent.db.addReward(u)

                # emit percent
                self.caller.sig_UTXOsLoading.emit(percent)
                curr_utxo += 1

            self.caller.sig_UTXOsLoading.emit(100)
            printDbg("--# REWARDS table updated")
            self.utxoLoaded = True
            self.caller.sig_UTXOsLoaded.emit()



    def onCancel(self):
        self.ui.rewardsList.box.clearSelection()
        self.selectedRewards = None
        self.ui.selectedRewardsLine.setText("0.0")
        self.suggestedFee = MINIMUM_FEE
        self.updateFee()
        self.AbortSend()



    def onChangeSelected(self):
        if self.ui.addySelect.currentIndex() >= 0:
            self.ui.resetStatusLabel()
            self.curr_path = self.ui.addySelect.itemData(self.ui.addySelect.currentIndex())[0]
            self.curr_addr = self.ui.addySelect.itemData(self.ui.addySelect.currentIndex())[1]
            self.curr_balance = self.ui.addySelect.itemData(self.ui.addySelect.currentIndex())[2]

            if self.curr_balance is not None:
                self.runInThread = ThreadFuns.runInThread(self.load_utxos_thread, (), self.display_utxos)



    def onSelectAllRewards(self):
        self.ui.rewardsList.box.selectAll()
        self.updateSelection()



    def onDeselectAllRewards(self):
        self.ui.rewardsList.box.clearSelection()
        self.updateSelection()



    def onSendRewards(self):
        self.dest_addr = self.ui.destinationLine.text().strip()

        # Check HW device
        if self.caller.hwStatus != 2:
            myPopUp_sb(self.caller, "crit", 'SPMT - hw device check', "Connect to HW device first")
            printDbg("Unable to connect to hardware device. The device status is: %d" % self.caller.hwStatus)
            return None

        # Check destination Address
        if not checkPivxAddr(self.dest_addr, self.caller.isTestnetRPC):
            myPopUp_sb(self.caller, "crit", 'SPMT - PIVX address check', "The destination address is missing, or invalid.")
            return None

        # LET'S GO
        if self.selectedRewards:
            printDbg("Sending from PIVX address  %s  to PIVX address  %s " % (self.curr_addr, self.dest_addr))
            printDbg("Preparing transaction. Please wait...")
            try:
                self.ui.loadingLine.show()
                self.ui.loadingLinePercent.show()
                QApplication.processEvents()
                self.currFee = self.ui.feeLine.value() * 1e8

                # save last destination address and swiftxCheck to cache and persist to settings
                self.caller.parent.cache["lastAddress"] = persistCacheSetting('cache_lastAddress', self.dest_addr)
                self.caller.parent.cache["useSwiftX"] = persistCacheSetting('cache_useSwiftX', self.useSwiftX())

                self.currFee = self.ui.feeLine.value() * 1e8
                # re-connect signals
                try:
                    self.caller.hwdevice.api.sigTxdone.disconnect()
                except:
                    pass
                try:
                    self.caller.hwdevice.api.sigTxabort.disconnect()
                except:
                    pass
                try:
                    self.caller.hwdevice.api.tx_progress.disconnect()
                except:
                    pass
                self.caller.hwdevice.api.sigTxdone.connect(self.FinishSend)
                self.caller.hwdevice.api.sigTxabort.connect(self.AbortSend)
                self.caller.hwdevice.api.tx_progress.connect(self.updateProgressPercent)

                try:
                    self.txFinished = False
                    self.caller.hwdevice.prepare_transfer_tx(self.caller, self.curr_path, self.selectedRewards,
                                                             self.dest_addr, self.currFee, self.useSwiftX(),
                                                             self.caller.isTestnetRPC)
                except DisconnectedException as e:
                    self.caller.hwStatus = 0
                    self.caller.updateHWleds()

                except Exception as e:
                    err_msg = "Error while preparing transaction. <br>"
                    err_msg += "Probably Blockchain wasn't synced when trying to fetch raw TXs.<br>"
                    err_msg += "<b>Wait for full synchronization</b> then hit 'Clear/Reload'"
                    printException(getCallerName(), getFunctionName(), err_msg, e.args)
            except Exception as e:
                print(e)
        else:
            myPopUp_sb(self.caller, "warn", 'Transaction NOT sent', "No UTXO to send")



    def removeSpentRewards(self):
        for utxo in self.selectedRewards:
            self.caller.parent.db.deleteReward(utxo['txid'], utxo['vout'])




    # Activated by signal sigTxdone from hwdevice
    def FinishSend(self, serialized_tx, amount_to_send):
        self.AbortSend()
        if not self.txFinished:
            try:
                self.txFinished = True
                tx_hex = serialized_tx.hex()
                printDbg("Raw signed transaction: " + tx_hex)
                printDbg("Amount to send :" + amount_to_send)

                if len(tx_hex) > 90000:
                    mess = "Transaction's length exceeds 90000 bytes. Select less UTXOs and try again."
                    self.caller.myPopUp2(QMessageBox.Warning, 'transaction Warning', mess)

                else:
                    decodedTx = None
                    try:
                        decodedTx = ParseTx(tx_hex, self.caller.isTestnetRPC)
                        destination = decodedTx.get("vout")[0].get("scriptPubKey").get("addresses")[0]
                        amount = decodedTx.get("vout")[0].get("value")
                        message = '<p>Broadcast signed transaction?</p><p>Destination address:<br><b>%s</b></p>' % destination
                        message += '<p>Amount: <b>%s</b> PIV<br>' % str(amount)
                        message += 'Fees: <b>%s</b> PIV <br>Size: <b>%d</b> Bytes</p>' % (
                        str(round(self.currFee / 1e8, 8)), len(tx_hex) / 2)
                    except Exception as e:
                        printException(getCallerName(), getFunctionName(), "decoding exception", str(e))
                        message = '<p>Unable to decode TX- Broadcast anyway?</p>'

                    mess1 = QMessageBox(QMessageBox.Information, 'Send transaction', message)
                    if decodedTx is not None:
                        mess1.setDetailedText(json.dumps(decodedTx, indent=4, sort_keys=False))
                    mess1.setStandardButtons(QMessageBox.Yes | QMessageBox.No)

                    reply = mess1.exec_()
                    if reply == QMessageBox.Yes:
                        txid = self.caller.rpcClient.sendRawTransaction(tx_hex, self.useSwiftX())
                        if txid is None:
                            raise Exception("Unable to send TX - connection to RPC server lost.")
                        mess2_text = "<p>Transaction successfully sent.</p>"
                        mess2 = QMessageBox(QMessageBox.Information, 'transaction Sent', mess2_text)
                        mess2.setDetailedText(txid)
                        mess2.exec_()
                        # remove spent rewards from DB
                        self.removeSpentRewards()
                        # reload utxos
                        self.display_utxos()
                        self.onCancel()

                    else:
                        myPopUp_sb(self.caller, "warn", 'Transaction NOT sent', "Transaction NOT sent")
                        self.onCancel()

            except Exception as e:
                err_msg = "Exception in FinishSend"
                printException(getCallerName(), getFunctionName(), err_msg, e.args)



    # Activated by signal sigTxabort from hwdevice
    def AbortSend(self):
        self.ui.loadingLine.hide()
        self.ui.loadingLinePercent.setValue(0)
        self.ui.loadingLinePercent.hide()



    def updateFee(self):
        if self.useSwiftX():
            self.ui.feeLine.setValue(0.01)
            self.ui.feeLine.setEnabled(False)
        else:
            self.ui.feeLine.setValue(self.suggestedFee)
            self.ui.feeLine.setEnabled(True)



    # Activated by signal tx_progress from hwdevice
    def updateProgressPercent(self, percent):
        self.ui.loadingLinePercent.setValue(percent)
        QApplication.processEvents()



    def updateSelection(self, clicked_item=None):
        total = 0
        self.selectedRewards = self.getSelection()
        numOfInputs = len(self.selectedRewards)
        if numOfInputs:
            for i in range(0, numOfInputs):
                total += int(self.selectedRewards[i].get('satoshis'))

            # update suggested fee and selected rewards
            estimatedTxSize = (44+numOfInputs*148)*1.0 / 1000   # kB
            feePerKb = self.caller.rpcClient.getFeePerKb()
            self.suggestedFee = round(feePerKb * estimatedTxSize, 8)
            printDbg("estimatedTxSize is %s kB" % str(estimatedTxSize))
            printDbg("suggested fee is %s PIV (%s PIV/kB)" % (str(self.suggestedFee), str(feePerKb)))

            self.ui.selectedRewardsLine.setText(str(round(total/1e8, 8)))

        else:
            self.ui.selectedRewardsLine.setText("")

        self.updateFee()



    def update_loading_utxos(self, percent):
        self.ui.resetStatusLabel('<em><b style="color:purple">Checking explorer... %d%%</b></em>' % percent)



    def useSwiftX(self):
        return self.ui.swiftxCheck.isChecked()

