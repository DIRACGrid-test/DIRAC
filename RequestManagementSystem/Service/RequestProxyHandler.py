########################################################################
# $HeadURL$
# File: RequestProxyHandler.py
# Author: Krzysztof.Ciba@NOSPAMgmail.com
# Date: 2012/07/20 13:18:41
########################################################################

""" :mod: RequestProxyHandler 
    =========================
 
    .. module: RequestProxyHandler
    :synopsis: RequestProxy service
    .. moduleauthor:: Krzysztof.Ciba@NOSPAMgmail.com

    Careful with that axe, Eugene! Some 'transfer' requests are using local fs 
    and they never should be forwarded to the central RequestManager.  
"""

__RCSID__ = "$Id$"

##
# @file RequestProxyHandler.py
# @author Krzysztof.Ciba@NOSPAMgmail.com
# @date 2012/07/20 13:18:58
# @brief Definition of RequestProxyHandler class.

## imports 
import os
import threading
from types import StringType
try:
  from hashlib import md5
except ImportError:
  from md5 import md5
## from DIRAC
from DIRAC import S_OK, S_ERROR, gLogger
from DIRAC.ConfigurationSystem.Client import PathFinder
from DIRAC.Core.DISET.RequestHandler import RequestHandler
from DIRAC.RequestManagementSystem.Client.RequestClient import RequestClient
from DIRAC.RequestManagementSystem.Client.RequestContainer import RequestContainer
from DIRAC.Core.Utilities.ThreadScheduler import gThreadScheduler

def initializeRequestProxyHandler( serviceInfo ):
  """ init RequestProxy handler 

  :param serviceInfo:
  """
  gLogger.info("Initalizing RequestProxyHandler")
  gThreadScheduler.addPeriodicTask( 10, RequestProxyHandler.sweeper )  
  return S_OK()

########################################################################
class RequestProxyHandler( RequestHandler ):
  """
  .. class:: RequestProxyHandler
  
  :param str centralURL: URL to central RequestManager handler
  :param RequestClient masterReqClient: master RequestManager
  :param str workDir: service WorkDirectory
  :param str cacheDir: os.path.join( workDir, "requestCache" )
  """
  __centralURL = None
  __requestClient = None
  __cacheDir = None

  def initialize( self ):
    """ service initialisation

    :param self: self reference
    """
    #self.workDir = self.getCSOption( "WorkDirectory" )
    #gLogger.notice( "WorkDirrectory           : %s" % self.workDir )
    gLogger.notice( "CacheDirirectory         : %s" % self.cacheDir() )
    gLogger.notice( "Master RequestManager URL: %s" % self.centralURL() )
    return S_OK()

  @classmethod
  def centralURL( cls ):
    """ get central RequestClient URL """
    if not cls.__centralURL:
      cls.__centralURL = PathFinder.getServiceURL( "RequestManagement/centralURL" )
      if not cls.__centralURL:
        raise RuntimeError("CS option for RequestManagement/centralURL is not set")
    return cls.__centralURL

  @classmethod
  def requestClient( cls ):
    """ get request client """
    if not cls.__requestClient:
      cls.__requestClient = RequestClient()
    return cls.__requestClient

  @classmethod
  def cacheDir( cls ):
    """ get cache dir """
    if not cls.__cacheDir:
      cls.__cacheDir = os.path.abspath( "requestCache" )
      if not os.path.exists( cls.__cacheDir ):
        os.mkdir( cls.__cacheDir )
    return cls.__cacheDir
                                          
  @classmethod
  def sweeper( cls ):
    """ move cached request to the central request manager
    
    :param self: self reference
    """
    cacheDir = cls.cacheDir()    
    ## cache dir empty? 
    if not os.listdir( cacheDir ):
      gLogger.always("sweeper: CacheDir %s is empty, nothing to do" % cacheDir )
      return S_OK()
    else:  
      ## read 10 cache dir files, the oldest first 
      cachedRequests = [ os.path.abspath( requestFile ) for requestFile in
                         sorted( filter( os.path.isfile,
                                         [ os.path.join( cacheDir, requestName ) 
                                           for requestName in os.listdir( cacheDir ) ] ),
                                 key = os.path.getctime ) ][:10]
      clientOK = True 
      ## set cached requests to the central RequestManager
      for cachedFile in cachedRequests:
        ## break if something went wrong last time
        if not clientOK:
          break
        try:
          requestString = "".join( open( cachedFile, "r" ).readlines() )
          cachedRequest = RequestContainer( requestString )
          requestName = cachedRequest.getAttribute("RequestName")["Value"]
          gLogger.always( requestName )
          gLogger.always( requestString )
          setRequest = cls.requestClient().setRequest( requestName, requestString, cls.centralURL() )
          if not setRequest["OK"]:
            gLogger.error("sweeper: unable to set request %s @ %s: %s" % ( requestName, 
                                                                           cls.centralURL(), 
                                                                           setRequest["Message"] ) )
            ## revert clientOK flag
            clientOK = False
            continue
          gLogger.info("sweeper: successfully set request %s @ %s" % ( requestName, cls.centralURL() ) )
          os.unlink( cachedFile )
        except Exception, error:
          gLogger.exception( "sweeper: hit by exception %s" % str(error) )
          return S_ERROR( "sweeper: hit by exception: %s" % str(error) )
      return S_OK()

  def __saveRequest( self, requestName, requestString ):
    """ save request string to the working dir cache 
    
    :param self: self reference
    :param str requestName: request name
    :param str requestString: xml-serialised request
    """
    try:
      requestFile = os.path.join( self.cacheDir(), md5(requestString).hexdigest() )
      request = open( requestFile, "w+")
      request.write( requestString )
      request.close()
      return S_OK( requestFile )
    except OSError, error:
      err = "unable to dump %s to cache file: %s" % ( requestName, str(error) )
      gLogger.exception( err )
      return S_ERROR( err )

  types_getStatus = []  
  def export_getStatus( self ):
    """ get number of requests in cache """
    try:
      cachedRequests = len( os.listdir( self.cacheDir() ) )
    except OSError, error:
      err = "getStatus: unable to list cache dir contents: %s" % str(error)
      gLogger.exception( err )
      return S_ERROR( err )
    return S_OK( cachedRequests )
                     
  types_setRequest = [ StringType, StringType ]
  def export_setRequest( self, requestName, requestString ):
    """ forward request from local RequestDB to central RequestClient

    :param self: self reference
    :param str requestType: request type
    """
    gLogger.info("setRequest: got '%s' request" %  requestName )
    forwardable = self.__forwardable( requestString )
    if not forwardable["OK"]:
      gLogger.error("setRequest: unable to forward %s: %s" % ( requestName, forwardable["Message"] ) )
      return forwardable

    setRequest = self.requestClient().setRequest( requestName, requestString, self.centralURL() )
    if not setRequest["OK"]:
      gLogger.error("setReqeuest: unable to set request '%s' @ %s: %s" % ( requestName,
                                                                           self.centralURL(),
                                                                           setRequest["Message"] ) )
      ## put request to the request file cache
      save = self.__saveRequest( requestName, requestString )
      if not save["OK"]:
        gLogger.error("setRequest: unable to save request to the cache: %s" % save["Message"] )
        return save
      gLogger.info("setRequest: %s is saved to %s file" % ( requestName, save["Value"] ) )
      return S_OK( { "set" : False, "saved" : True } )
    
    gLogger.info("setRequest: request '%s' has been set to %s" % ( requestName, self.centralURL() ) )
    return S_OK( { "set" : True, "saved" : False } )

  @staticmethod
  def __forwardable( requestString ):
    """ check if request if forwardable 

    The sub-request of type transfer:putAndRegister, removal:physicalRemoval and removal:reTransfer are
    definitely not, they should be executed locally, as they are using local fs.

    :param str requestString: XML-serialised request
    """
    request = RequestContainer( requestString )
    subRequests = request.getSubRequests( "transfer" )["Value"] + request.getSubRequests( "removal" )["Value"]
    for subRequest in subRequests:
      if subRequest["Attributes"]["Operation"] in ( "putAndRegister", "physicalRemoval", "reTransfer" ):
        return S_ERROR("found operation '%s' that cannot be forwarded" % subRequest["Attributes"]["Operation"] )
    return S_OK()
