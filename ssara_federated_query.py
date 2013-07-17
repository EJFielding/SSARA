#! /usr/bin/env python
###############################################################################
# ssara_federated_query.py
#
#  Project:  Seamless SAR Archive
#  Purpose:  Command line federated query client
#  Author:   Scott Baker
#  Created:  June 2013
#
###############################################################################
#  Copyright (c) 2013, Scott Baker 
# 
#  Permission is hereby granted, free of charge, to any person obtaining a
#  copy of this software and associated documentation files (the "Software"),
#  to deal in the Software without restriction, including without limitation
#  the rights to use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of the Software, and to permit persons to whom the
#  Software is furnished to do so, subject to the following conditions:
# 
#  The above copyright notice and this permission notice shall be included
#  in all copies or substantial portions of the Software.
# 
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
#  OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#  THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
###############################################################################

import os
import sys
import urllib
import urllib2
import json
import datetime
import time
import csv
from xml.dom import minidom
import itertools
import operator
import re
import optparse
import threading
import Queue


class MyParser(optparse.OptionParser):
    def format_epilog(self, formatter):
        return self.epilog
    def format_description(self, formatter):
        return self.description
    
def main(argv):
    ### READ IN PARAMETERS FROM THE COMMAND LINE ###
    desc = """Command line client for searching with the SSARA Federated API, 
creating KMLs, and downloading data.  See the options and 
descriptions below for details and usage examples.

For questions or comments, contact Scott Baker: baker@unavco.org
    """
    epi = """
Usage Examples:
  These will do the search and create a KML:
    ssara_federated_query.py --platform=ENVISAT -r 170 -f 2925 --kml
    ssara_federated_query.py --platform=ENVISAT -r 170,392 -f 2925,657-693 -s 2003-01-01 -e 2008-01-01 --kml
    ssara_federated_query.py --platform=ENVISAT,ERS-1,ERS-2 -r 170 -f 2925 --collectionName="WInSAR ESA,EarthScope ESA" --kml
    ssara_federated_query.py --platform=ENVISAT --intersectsWith=POLYGON((-118.3 33.7, -118.3 33.8, -118.0 33.8, -118.0 33.7, -118.3 33.7)) --kml
    
  To download data, add the --download option and your user credentials (--unavuser=/--unavpass= for UNAVCO, --asfuser=/--asfpass= for ASF, and --ssuser=/--sspass= for Supersites)
    ssara_federated_query.py --platform=ENVISAT -r 170 -f 2925 --download --unavuser=USERNAME --unavpass=PASSWORD
    ssara_federated_query.py --platform=ENVISAT -r 170,392 -f 2925,657-693 -s 2003-01-01 -e 2008-01-01 --download --unavuser=USERNAME --unavpass=PASSWORD
    ssara_federated_query.py --platform=ENVISAT,ERS-1,ERS-2 -r 170 -f 2925 --collection="WInSAR ESA,EarthScope ESA" --download --unavuser=USERNAME --unavpass=PASSWORD
"""
    parser = MyParser(description=desc, epilog=epi, version='0.1rc1')
    querygroup = optparse.OptionGroup(parser, "Query Parameters", "These options are used for the API query.  "  
                                      "Use options to limit what is returned by the search. These options act as a way "
                                      "to filter the results and narrow down the search results.")
    
    querygroup.add_option('-p','--platform', action="store", dest="platform", metavar='<ARG>', default='', help='List of platforms (ie ALOS, ENVISAT, ERS-2...')
    querygroup.add_option('-a','--absoluteOrbit', action="store", dest="absoluteOrbit", metavar='<ARG>', default='',help='Absolute orbit (single orbit or list)')                      
    querygroup.add_option('-r', '--relativeOrbit', action="store", dest="relativeOrbit", metavar='<ARG>', default='',help='Relative Orbit (ie track or path)')  
    querygroup.add_option('-i','--intersectsWith', action="store", dest="intersectsWith", metavar='<ARG>', default='',help='WKT format POINT,LINE, or POLYGON')
    querygroup.add_option('-f', '--frame', action="store", dest="frame", metavar='<ARG>', default='',help='frame(s) (single frame or as a list or range)')  
    querygroup.add_option('-s', '--start', action="store", dest="start", metavar='<ARG>', default='',help='start date for acquisitions')
    querygroup.add_option('-e', '--end', action="store", dest="end", metavar='<ARG>', default='',help='end date for acquisitions')
    querygroup.add_option('--beamMode', action="store", dest="beamMode", metavar='<ARG>', default='',help='list of beam modes')  
    querygroup.add_option('--beamSwath', action="store", dest="beamSwath", metavar='<ARG>', default='',help='list of swaths: S1, S2, F1, F4...')
    querygroup.add_option('--flightDirection', action="store", dest="flightDirection", metavar='<ARG>', default='',help='Flight Direction (A or D, default is both)')
    querygroup.add_option('--lookDirection', action="store", dest="lookDirection", metavar='<ARG>', default='',help='Look Direction (L or R, default is both)')
    querygroup.add_option('--polarization', action="store", dest="polarization", metavar='<ARG>', default='',help='single or as a list')
    querygroup.add_option('--collectionName', action="store", dest="collectionName", metavar='<ARG>', default='',help='single collection or list of collections')  
    querygroup.add_option('--processingLevel', action="store", dest="processingLevel", help='L0, L1, L1.0... (default=%default)', default='L1.0,L0')
    querygroup.add_option('--maxResults', action="store", dest="maxResults", type="int", metavar='<ARG>', help='maximum number of results to return (from each archive)')
    parser.add_option_group(querygroup)

    resultsgroup = optparse.OptionGroup(parser, "Result Options", "These options handle the results returned by the API query")
    resultsgroup.add_option('--kml', action="store_true", default=False, help='create a KML of query') 
    resultsgroup.add_option('--print', action="store_true", default=False, help='print results to screen')
    resultsgroup.add_option('--download', action="store_true", default=False, help='download the data')
    resultsgroup.add_option('--parallel', action="store", dest="parallel", type="int", default=1, metavar='<ARG>', help='number of scenes to download in parallel (default=%default)')
    resultsgroup.add_option('--unavuser', action="store", dest="unavuser", type="str", metavar='<ARG>', help='UNAVCO SAR Archive username')
    resultsgroup.add_option('--unavpass', action="store", dest="unavpass", type="str",metavar='<ARG>', help='UNAVCO SAR Archive password')
    resultsgroup.add_option('--asfuser', action="store", dest="asfuser", type="str", metavar='<ARG>', help='ASF Archive username')
    resultsgroup.add_option('--asfpass', action="store", dest="asfpass", type="str", metavar='<ARG>', help='ASF Archive password')
    resultsgroup.add_option('--ssuser', action="store", dest="ssuser", type="str", metavar='<ARG>', help='Supersites username')
    resultsgroup.add_option('--sspass', action="store", dest="sspass", type="str", metavar='<ARG>', help='Supersites password')
    parser.add_option_group(resultsgroup) 
    opts, remainder = parser.parse_args(argv)
    opt_dict= vars(opts)
    query_dict = {}
    for k,v in opt_dict.iteritems():
        if v:
            query_dict[k] = v

    ### QUERY THE APIs AND GET THE JSON RESULTS ###
    params = urllib.urlencode(query_dict)
    ssara_url = "http://www.unavco.org/ws/brokered/ssara/sar/search?%s" % params
    print "Running SSARA API Query"
    t = time.time()
    f = urllib2.urlopen(ssara_url)
    json_data = f.read()
    scenes = json.loads(json_data)
    print "SSARA API query: %f seconds" % (time.time()-t)

    ### ORDER THE SCENES BY STARTTIME, NEWEST FIRST ###
    scenes = sorted(scenes, key=operator.itemgetter('startTime'), reverse=True)
    print "Found %d scenes" % len(scenes)
    
    if not opt_dict['kml'] and not opt_dict['download'] and not opt_dict['print']:
        print "You did not specify the --kml, --print, or --download option, so there really is nothing else I can do for you now"
    if opt_dict['print']:
        for r in sorted(scenes, key=operator.itemgetter('startTime')):
            print ",".join(str(x) for x in [r['collectionName'], r['platform'], r['absoluteOrbit'], r['startTime'], r['stopTime'], r['relativeOrbit'], r['firstFrame'], r['finalFrame'], r['beamMode'], r['beamSwath'], r['flightDirection'], r['lookDirection'],r['polarization'], r['downloadUrl']])
    ### GET A KML FILE, THE FEDERATED API HAS THIS OPTION ALREADY, SO MAKE THE SAME CALL AGAIN WITH output=kml OPTION ###
    if opt_dict['kml']:
        ssara_url = "http://www.unavco.org/ws/brokered/ssara/sar/search?output=kml&%s" % params
        print "Getting KML"
        t = time.time()
        req = urllib2.Request(ssara_url)
        r = urllib2.urlopen(req)
        localName = r.info()['Content-Disposition'].split('filename=')[1].replace('"','')
        print "Saving KML: %s" % localName
        f = open(localName, 'wb')
        f.write(r.read())
        f.close() 
    ### DOWNLOAD THE DATA FROM THE QUERY RESULTS ### 
    if opt_dict['download']:
        #a couple quick checks to make sure everything is in order
        allGood = True
        for collection in list(set([d['collectionName'] for d in scenes])):
            if ('WInSAR' in collection or 'EarthScope' in collection) and not (opt_dict['unavuser'] and opt_dict['unavpass'] ):
                print "Can't download collection: %s" % collection
                print "You need to specify your UNAVCO username and password as options (--username=<ARG> and --password=<ARG>)"
                print "If you don't have a UNAVCO username/password, limit the query with the --collection option\n"
                allGood = False
            if 'Supersites' in collection and not (opt_dict['ssuser']  and opt_dict['sspass']):
                print "\n****************************************************************"
                print "For the Supersites data, you need an EO Single Sign On username/password:"
                print "Sign up for one here: https://eo-sso-idp.eo.esa.int/idp/AuthnEngine"
                print "The SSO Downloader is need to download the data."
                print "Get the downloader here: http://supersites.earthobservations.org/sso-downloader-0.1.tar.gz"
                print "****************************************************************\n"
            if 'ASF' in collection and not (opt_dict['asfuser'] and opt_dict['asfpass'] ):
                print "Can't download collection: %s" % collection
                print "You need to specify your ASF username and password as options (--asfuser=<ARG> and --asfpass=<ARG>)"
                print "If you don't have a ASF username/password, limit the query with the --collection option\n"
                allGood = False
        if not allGood:
            print "Exiting now since some username/password are need for data download to continue"
            exit()
        print "Downloading data now, %d at a time." % opt_dict['parallel']
        #create a queue for parallel downloading
        queue = Queue.Queue()
        #spawn a pool of threads, and pass them queue instance 
        for i in range(opt_dict['parallel']):
            t = ThreadDownload(queue)
            t.setDaemon(True)
            t.start()
        #populate queue with data   
        for d in sorted(scenes, key=operator.itemgetter('collectionName')):
            if d['collectionName'] == 'Supersites':
                if 'archive4' in d['downloadUrl']:
                    print "ssod -d . -u $ARCHIVE4_USERNAME -p $ARCHIVE4_PASSWORD %s" % d['downloadUrl']
                elif 'archive2' in d['downloadUrl']:
                    print "wget --user=$SUPERSITES_USERNAME --password=$SUPERSITES_PASSWORD %s" % d['downloadUrl']
            else:
                queue.put([d, opt_dict])
        #wait on the queue until everything has been processed     
        queue.join()
        
        
def asf_dl(d, opt_dict):
    user_name = opt_dict['asfuser']
    user_password = opt_dict['asfpass']
    url = d['downloadUrl']
    filename = os.path.basename(url)
    o = urllib2.build_opener( urllib2.HTTPCookieProcessor() )
    urllib2.install_opener(o)
    p = urllib.urlencode({'user_name':user_name,'user_password':user_password})
    o.open("https://ursa.asfdaac.alaska.edu/cgi-bin/login",p)
    try:
        f = o.open(url)
    except urllib2.HTTPError, e:
        print 'Problem with:',url
        print e
        log = open('missing.txt','a')
        log.write(filename + '\n')
        log.close()
        exit()
    dl_file_size = int(f.info()['Content-Length'])
    if os.path.exists(filename):
        file_size = os.path.getsize(filename)
        if dl_file_size == file_size:
            print "%s already downloaded" % filename
            f.close()
            return
    print "ASF Download:",filename
    start = time.time()
    CHUNK = 256 * 10240
    with open(filename, 'wb') as fp:
        while True:
            chunk = f.read(CHUNK)
            if not chunk: break
            fp.write(chunk)
    total_time = time.time()-start
    mb_sec = (os.path.getsize(filename)/(1024*1024.0))/total_time
    print "%s download time: %.2f secs (%.2f MB/sec)" %(filename,total_time,mb_sec)
    f.close()
        
def unavco_dl(d, opt_dict):
    user_name = opt_dict['unavuser']
    user_password = opt_dict['unavpass']
    url = d['downloadUrl']
    passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
    passman.add_password(None, 'http://facility.unavco.org/data/sar/', user_name, user_password)
    authhandler = urllib2.HTTPDigestAuthHandler(passman)
    opener = urllib2.build_opener(authhandler)    
    filename = os.path.basename(url)
    try:
        f = opener.open(url)
    except urllib2.HTTPError, e:
        print e
        return
    dl_file_size = int(f.info()['Content-Length'])
    if os.path.exists(filename):
        file_size = os.path.getsize(filename)
        if dl_file_size == file_size:
            print "%s already downloaded" % filename
            f.close()
            return
    start = time.time()
    with open(filename, 'wb') as T:
        T.write(f.read())
    total_time = time.time() - start
    mb_sec = (os.path.getsize(filename) / (1024 * 1024.0)) / total_time
    print "%s download time: %.2f secs (%.2f MB/sec)" % (filename, total_time, mb_sec)
    f.close()
    
class ThreadDownload(threading.Thread):
    """Threaded SAR data download"""
    def __init__(self, queue):
        threading.Thread.__init__(self)
        self.queue = queue

    def run(self):
        while True:
            d, opt_dict = self.queue.get()
            if d['collectionName'] == 'WInSAR ESA' or 'EarthScope' in d['collectionName'] or 'TSX ' in d['collectionName']: 
                unavco_dl(d, opt_dict)
            elif d['collectionName'] == 'Supersites': 
                print "Supersite download not working directly form the client at this time"
                print "Please run the ssod commands separately"
            elif 'ASF' in d['collectionName'] :
                asf_dl(d, opt_dict)
            self.queue.task_done()
             
if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.argv.append('-h')
    main(sys.argv[1:])
