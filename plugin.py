import os, sys
from datetime import datetime
from pathlib import Path
from qgis.PyQt.QtCore import Qt, QVariant, QSettings, QUrl, QObject, QEvent
from qgis.PyQt.QtGui import QColor, QKeySequence, QDesktopServices
from qgis.PyQt.QtWidgets import QAction,QApplication,QComboBox,QDialog,QDialogButtonBox,QDockWidget,QFileDialog,QFormLayout,QHBoxLayout,QLabel,QKeySequenceEdit,QLineEdit,QMessageBox,QPlainTextEdit,QPushButton,QShortcut,QSpinBox,QVBoxLayout,QWidget
from qgis.core import Qgis,QgsFeatureRequest,QgsField,QgsGeometry,QgsPointXY,QgsProject,QgsVectorFileWriter,QgsVectorLayer,QgsWkbTypes
from qgis.gui import QgsMapToolEmitPoint,QgsRubberBand
try:
 from qgis.PyQt.QtWebEngineWidgets import QWebEngineView
except ImportError: QWebEngineView=None
try:
 from qgis.gui import QgsWebView
except ImportError: QgsWebView=None
KEYS={'accept':'A','move':'M','reject':'R','previous':'P','source':'O','cancel':'Esc'}
FIELDS=[QgsField('rev_status',QVariant.String,len=16),QgsField('rev_note',QVariant.String,len=254),QgsField('rev_date',QVariant.String,len=25),QgsField('orig_x',QVariant.Double,len=20,prec=10),QgsField('orig_y',QVariant.Double,len=20,prec=10)]
class KeyDialog(QDialog):
 def __init__(self,settings,parent):
  super().__init__(parent);self.s=settings;self.setWindowTitle('Reviewer Settings');v=QVBoxLayout(self);f=QFormLayout();self.e={}
  for k,d in KEYS.items():x=QKeySequenceEdit(QKeySequence(settings.value('keys/'+k,d)));self.e[k]=x;f.addRow(k.replace('_',' ').title()+':',x)
  v.addLayout(f);b=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel|QDialogButtonBox.RestoreDefaults);v.addWidget(b);b.accepted.connect(self.save);b.rejected.connect(self.reject);b.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.restore)
 def restore(self):
  for k,d in KEYS.items():self.e[k].setKeySequence(QKeySequence(d))
 def save(self):
  vals=[x.keySequence().toString() for x in self.e.values() if x.keySequence().toString()]
  if len(vals)!=len(set(vals)):QMessageBox.warning(self,'Duplicate shortcuts','Each shortcut must be unique.');return
  for k,x in self.e.items():self.s.setValue('keys/'+k,x.keySequence().toString())
  self.accept()
class Reviewer(QObject):
 def __init__(self,iface):
  super().__init__();self.iface=iface;self.s=QSettings('OccurrenceReviewer','OccurrenceReviewer');self.action=self.dock=self.webdock=self.web=self.debugdock=self.debugtext=None;self.layer=None;self.ids=[];self.i=-1;self.tool=self.oldtool=self.band=None;self.shortcuts=[];self.key_actions={};self.debug_lines=[];QApplication.instance().installEventFilter(self)
 def msg(self,t,l=Qgis.Info):self.iface.messageBar().pushMessage('Occurrence Reviewer',t,level=l,duration=6)
 def initGui(self):self.action=QAction('Occurrence Reviewer',self.iface.mainWindow());self.action.triggered.connect(self.show);self.iface.addPluginToVectorMenu('Occurrence Reviewer',self.action);self.iface.addToolBarIcon(self.action)
 def unload(self):
  QApplication.instance().removeEventFilter(self);self.cancel();self.clear()
  for d in (self.debugdock,self.webdock,self.dock):
   if d:self.iface.removeDockWidget(d);d.deleteLater()
  self.iface.removePluginVectorMenu('Occurrence Reviewer',self.action);self.iface.removeToolBarIcon(self.action)
 def show(self):
  if not self.dock:self.build()
  self.refresh();self.dock.show()
 def build(self):
  self.dock=QDockWidget('Occurrence Reviewer',self.iface.mainWindow());w=QWidget();v=QVBoxLayout(w);f=QFormLayout();self.layers=QComboBox();self.layers.currentIndexChanged.connect(self.changed);self.urls=QComboBox();self.scale=QSpinBox();self.scale.setRange(100,1000000);self.scale.setValue(2000);self.scale.setPrefix('1:');f.addRow('Point layer:',self.layers);f.addRow('Source field:',self.urls);f.addRow('Scale:',self.scale);v.addLayout(f)
  r=QHBoxLayout();a=QPushButton('Start / resume');a.clicked.connect(self.start);refresh=QPushButton('Refresh layers');refresh.clicked.connect(self.refresh);b=QPushButton('Settings');b.clicked.connect(self.settings);r.addWidget(a);r.addWidget(refresh);r.addWidget(b);v.addLayout(r);self.progress=QLabel('Ready');self.info=QLabel();self.info.setWordWrap(True);self.note=QLineEdit();self.note.setPlaceholderText('Optional note');v.addWidget(self.progress);v.addWidget(self.info);v.addWidget(self.note)
  o=QPushButton('Open source');o.clicked.connect(self.source);v.addWidget(o);r=QHBoxLayout();a=QPushButton('Accept');a.clicked.connect(lambda:self.decide('accepted'));m=QPushButton('Move');m.clicked.connect(self.move);x=QPushButton('Reject');x.clicked.connect(lambda:self.decide('rejected'));r.addWidget(a);r.addWidget(m);r.addWidget(x);v.addLayout(r);p=QPushButton('Previous');p.clicked.connect(self.previous);v.addWidget(p);z=QPushButton('Finish review and export clean layer');z.clicked.connect(self.finish);v.addWidget(z);d=QPushButton('Show debug log');d.clicked.connect(self.show_debug);v.addWidget(d);v.addStretch();self.dock.setWidget(w);self.iface.addDockWidget(Qt.RightDockWidgetArea,self.dock);self.bind()
 def settings(self):
  if KeyDialog(self.s,self.iface.mainWindow()).exec_()==QDialog.Accepted:self.bind()
 def log(self,message):
  line='{} | {}'.format(datetime.now().isoformat(timespec='milliseconds'),message)
  self.debug_lines.append(line)
  if len(self.debug_lines)>2000:self.debug_lines=self.debug_lines[-2000:]
  if self.debugtext:self.debugtext.appendPlainText(line)
 def show_debug(self):
  if not self.debugdock:
   self.debugdock=QDockWidget('Occurrence Reviewer Debug Log',self.iface.mainWindow());w=QWidget();v=QVBoxLayout(w);self.debugtext=QPlainTextEdit();self.debugtext.setReadOnly(True);self.debugtext.setPlainText('\n'.join(self.debug_lines));v.addWidget(self.debugtext);r=QHBoxLayout();save=QPushButton('Save log');save.clicked.connect(self.save_debug);clear=QPushButton('Clear log');clear.clicked.connect(self.clear_debug);r.addWidget(save);r.addWidget(clear);v.addLayout(r);self.debugdock.setWidget(w);self.iface.addDockWidget(Qt.BottomDockWidgetArea,self.debugdock)
  self.debugdock.show();self.debugdock.raise_();self.log('Debug panel opened')
 def save_debug(self):
  path,_=QFileDialog.getSaveFileName(self.iface.mainWindow(),'Save diagnostic log',os.path.expanduser('~/occurrence_reviewer_debug.txt'),'Text files (*.txt)')
  if path:
   Path(path).write_text('\n'.join(self.debug_lines),encoding='utf-8');self.msg('Debug log saved to '+path,Qgis.Success)
 def clear_debug(self):
  self.debug_lines=[]
  if self.debugtext:self.debugtext.clear()
 def bind(self):
  # Store configured keys for direct event handling. This avoids QGIS shortcut conflicts and ambiguous QShortcut activation.
  self.key_actions={}
  calls={'accept':lambda:self.decide('accepted'),'move':self.move,'reject':lambda:self.decide('rejected'),'previous':self.previous,'source':self.source,'cancel':self.cancel}
  for name,fn in calls.items():
   text=str(self.s.value('keys/'+name,KEYS[name]) or '').strip()
   if text:self.key_actions[QKeySequence(text).toString()]=fn
  self.log('Key bindings loaded: '+', '.join(sorted(self.key_actions.keys())))
 def configured_action(self,event):
  sequence=QKeySequence(int(event.modifiers()) | event.key()).toString()
  return sequence,self.key_actions.get(sequence)
 def eventFilter(self,obj,event):
  if not self.dock or not self.dock.isVisible():return super().eventFilter(obj,event)
  if event.type() not in (QEvent.ShortcutOverride,QEvent.KeyPress):return super().eventFilter(obj,event)
  focus=QApplication.focusWidget();focus_name=focus.metaObject().className() if focus else 'None';obj_name=obj.metaObject().className() if hasattr(obj,'metaObject') else type(obj).__name__
  sequence,action=self.configured_action(event)
  self.log('event={} key={} sequence={} matched={} focus={} receiver={} autorepeat={} current={} tool={}'.format('ShortcutOverride' if event.type()==QEvent.ShortcutOverride else 'KeyPress',event.key(),sequence,bool(action),focus_name,obj_name,getattr(event,'isAutoRepeat',lambda:False)(),self.i,type(self.iface.mapCanvas().mapTool()).__name__))
  if isinstance(focus,(QLineEdit,QKeySequenceEdit)):
   self.log('event ignored because a text/key editor has focus');return False
  if event.type()==QEvent.ShortcutOverride and action:
   event.accept();self.log('shortcut override claimed for '+sequence);return True
  if event.type()==QEvent.KeyPress and action and not event.isAutoRepeat():
   self.log('executing action for '+sequence);action();event.accept();return True
  return super().eventFilter(obj,event)
 def refresh(self):
  old=self.layers.currentData();self.layers.blockSignals(True);self.layers.clear();count=0
  for l in QgsProject.instance().mapLayers().values():
   if isinstance(l,QgsVectorLayer) and QgsWkbTypes.geometryType(l.wkbType())==QgsWkbTypes.PointGeometry:
    self.layers.addItem(l.name(),l.id());count+=1
  j=self.layers.findData(old)
  if j>=0:self.layers.setCurrentIndex(j)
  elif self.layers.count()>0:self.layers.setCurrentIndex(0)
  self.layers.blockSignals(False);self.changed();self.log('Layer finder refreshed: {} point layer(s) found; selected={}'.format(count,self.layers.currentText() if count else None))
  if self.dock and self.dock.isVisible():self.msg('Layer list refreshed: {} point layer(s) found.'.format(count),Qgis.Success if count else Qgis.Warning)
 def changed(self):
  self.layer=QgsProject.instance().mapLayer(self.layers.currentData()) if self.layers.count() else None;self.urls.clear();self.urls.addItem('Auto-detect','');self.ids=[];self.i=-1
  if self.layer:
   for f in self.layer.fields():self.urls.addItem(f.name(),f.name())
   self.progress.setText('Selected: {} ({} points)'.format(self.layer.name(),self.layer.featureCount()))
 def gpkg(self):return self.layer and self.layer.providerType()=='ogr' and self.layer.source().lower().split('|')[0].endswith('.gpkg')
 def start(self):
  self.log('Start clicked layer={} provider={} source={}'.format(self.layer.name() if self.layer else None,self.layer.providerType() if self.layer else None,self.layer.source() if self.layer else None))
  if not self.gpkg():QMessageBox.critical(self.iface.mainWindow(),'GeoPackage required','Export the point layer to a writable GeoPackage, load that layer, and try again.');return
  if not self.layer.isEditable() and not self.layer.startEditing():self.msg('The GeoPackage layer is not writable.',Qgis.Critical);return
  have={f.name() for f in self.layer.fields()}
  for f in FIELDS:
   if f.name() not in have and not self.layer.addAttribute(f):self.msg('Could not add '+f.name(),Qgis.Critical);return
  self.layer.updateFields();self.ids=sorted(f.id() for f in self.layer.getFeatures() if f.hasGeometry() and not f.geometry().isEmpty())
  if not self.ids:self.msg('No valid point geometry found.',Qgis.Warning);return
  self.i=0
  for j,fid in enumerate(self.ids):
   if str(self.get(fid)['rev_status'] or '').lower() not in ('accepted','moved','rejected'):self.i=j;break
  self.display()
 def get(self,fid):return next(self.layer.getFeatures(QgsFeatureRequest().setFilterFid(fid)),None)
 def current(self):return self.get(self.ids[self.i]) if self.ids and 0<=self.i<len(self.ids) else None
 def display(self):
  f=self.current();self.layer.selectByIds([f.id()]);p=f.geometry().asPoint();mp=self.iface.mapCanvas().mapSettings().layerToMapCoordinates(self.layer,QgsPointXY(p));self.iface.mapCanvas().setCenter(mp);self.iface.mapCanvas().zoomScale(self.scale.value());self.highlight(mp);self.progress.setText('Record {} of {}'.format(self.i+1,len(self.ids)));self.info.setText('Feature ID: {}\nStatus: {}\nSource: {}'.format(f.id(),f['rev_status'] or 'unreviewed',self.url(f) or 'not detected'));self.note.setText(str(f['rev_note'] or ''))
 def original(self,f):
  if f['orig_x'] in (None,'') or f['orig_y'] in (None,''):
   p=f.geometry().asPoint();self.layer.changeAttributeValue(f.id(),self.layer.fields().indexOf('orig_x'),p.x());self.layer.changeAttributeValue(f.id(),self.layer.fields().indexOf('orig_y'),p.y())
 def decide(self,status):
  f=self.current()
  if not f:self.msg('Start the review first.',Qgis.Warning);return
  self.original(f)
  for n,v in [('rev_status',status),('rev_note',self.note.text()),('rev_date',datetime.now().isoformat(timespec='seconds'))]:self.layer.changeAttributeValue(f.id(),self.layer.fields().indexOf(n),v)
  self.next()
 def next(self):
  if self.i<len(self.ids)-1:self.i+=1;self.display()
  else:self.msg('Final point reviewed. Use Finish review.',Qgis.Success)
 def previous(self):
  if self.i>0:self.i-=1;self.display()
 def move(self):
  self.log('move invoked current_index={} current_fid={} existing_tool={} canvas_tool={}'.format(self.i,self.current().id() if self.current() else None,type(self.tool).__name__ if self.tool else None,type(self.iface.mapCanvas().mapTool()).__name__))
  if not self.current():self.msg('Start the review first.',Qgis.Warning);return
  self.oldtool=self.iface.mapCanvas().mapTool();self.tool=QgsMapToolEmitPoint(self.iface.mapCanvas());self.tool.canvasClicked.connect(self.moved);self.iface.mapCanvas().setMapTool(self.tool);self.msg('Move mode active: click the corrected map position.',Qgis.Info);self.log('move tool installed oldtool={} newtool={} canvas_tool={}'.format(type(self.oldtool).__name__,type(self.tool).__name__,type(self.iface.mapCanvas().mapTool()).__name__))
 def moved(self,p,b):
  self.log('canvasClicked button={} point=({}, {}) current_index={}'.format(int(b),p.x(),p.y(),self.i))
  if b!=Qt.LeftButton:self.log('move click ignored: not left button');return
  f=self.current();self.original(f);lp=self.iface.mapCanvas().mapSettings().mapToLayerCoordinates(self.layer,QgsPointXY(p));self.layer.changeGeometry(f.id(),QgsGeometry.fromPointXY(lp))
  for n,v in [('rev_status','moved'),('rev_note',self.note.text()),('rev_date',datetime.now().isoformat(timespec='seconds'))]:self.layer.changeAttributeValue(f.id(),self.layer.fields().indexOf(n),v)
  self.log('geometry changed and record marked moved');self.cancel();self.next()
 def cancel(self):
  self.log('cancel called tool={} oldtool={} canvas_tool={}'.format(type(self.tool).__name__ if self.tool else None,type(self.oldtool).__name__ if self.oldtool else None,type(self.iface.mapCanvas().mapTool()).__name__))
  if self.tool:
   try:self.tool.canvasClicked.disconnect(self.moved)
   except Exception:pass
   if self.oldtool:self.iface.mapCanvas().setMapTool(self.oldtool)
   self.tool=self.oldtool=None;self.log('cancel complete canvas_tool={}'.format(type(self.iface.mapCanvas().mapTool()).__name__))
 def url(self,f):
  names={x.name().lower():x.name() for x in self.layer.fields()};chosen=self.urls.currentData();c=[chosen] if chosen else ['references','reference','url','occurrenceid','inat_url']
  for k in c:
   n=names.get(str(k).lower())
   if n:
    u=str(f[n] or '').strip()
    if u.startswith(('http://','https://')):return u
  for k,base in [('inaturalist_id','https://www.inaturalist.org/observations/'),('inat_id','https://www.inaturalist.org/observations/'),('gbifid','https://www.gbif.org/occurrence/'),('key','https://www.gbif.org/occurrence/')]:
   n=names.get(k)
   if n and f[n] not in (None,''):return base+str(f[n])
 def source(self):
  f=self.current();u=self.url(f) if f else None
  if not u:self.msg('No source URL detected.',Qgis.Warning);return
  cls=QgsWebView if sys.platform.startswith('linux') else (QWebEngineView or QgsWebView)
  if not cls:QDesktopServices.openUrl(QUrl(u));self.msg('Source opened in the system browser; QGIS cannot close external tabs.',Qgis.Warning);return
  if not self.webdock:self.webdock=QDockWidget('Occurrence Source',self.iface.mainWindow());self.web=cls();self.webdock.setWidget(self.web);self.iface.addDockWidget(Qt.LeftDockWidgetArea,self.webdock)
  if hasattr(self.web,'stop'):self.web.stop()
  if hasattr(self.web,'setUrl'):self.web.setUrl(QUrl('about:blank'));self.web.setUrl(QUrl(u))
  else:self.web.load(QUrl(u))
  self.webdock.show();self.webdock.raise_()
 def finish(self):
  if not self.layer:return
  if self.layer.isEditable() and not self.layer.commitChanges():QMessageBox.critical(self.iface.mainWindow(),'Save failed','Could not commit edits.');return
  base=''.join(c if c.isalnum() or c=='_' else '_' for c in self.layer.name()).strip('_') or 'occurrences';name=base+'_reviewed';path,_=QFileDialog.getSaveFileName(self.iface.mainWindow(),'Export clean layer',os.path.expanduser('~/'+name+'.gpkg'),'GeoPackage (*.gpkg)')
  if not path:return
  if not path.endswith('.gpkg'):path+='.gpkg'
  clean=self.layer.materialize(QgsFeatureRequest().setFilterExpression('"rev_status" IN (\'accepted\',\'moved\')'));o=QgsVectorFileWriter.SaveVectorOptions();o.driverName='GPKG';o.layerName=name;o.actionOnExistingFile=QgsVectorFileWriter.CreateOrOverwriteFile;r=QgsVectorFileWriter.writeAsVectorFormatV3(clean,path,QgsProject.instance().transformContext(),o)
  if r[0]!=QgsVectorFileWriter.NoError:QMessageBox.critical(self.iface.mainWindow(),'Export failed',str(r));return
  out=QgsVectorLayer(path+'|layername='+name,name,'ogr')
  if out.isValid():QgsProject.instance().addMapLayer(out)
 def highlight(self,p):self.clear();self.band=QgsRubberBand(self.iface.mapCanvas(),QgsWkbTypes.PointGeometry);self.band.setColor(QColor(255,40,40));self.band.setIcon(QgsRubberBand.ICON_CIRCLE);self.band.setIconSize(18);self.band.addPoint(p)
 def clear(self):
  if self.band:self.band.reset(QgsWkbTypes.PointGeometry);self.band=None
