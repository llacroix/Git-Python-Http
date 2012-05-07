# Our tutorial's WSGI server
from wsgiref.simple_server import make_server
from webob import Request, Response
import re
from subprocess import Popen, PIPE
from datetime import datetime

from logging import getLogger
log = getLogger(__name__)


class Error(BaseException, Response):
    def __init__(self, *args, **kargs):
        Response.__init__(self, *args, **kargs)
        self.content_type = 'text/plain'


class NotFound(Error):
    def __init__(self, *args, **kargs):
        Error.__init__(self, *args, **kargs)
        self.status = 404
        self.body = "Not found"
 
class Forbidden(Error):
    def __init__(self, *args, **kargs):
        Error.__init__(self, *args, **kargs)
        self.status = 403
        self.body = "Forbidden"

views = []

def action(regex, method="GET", rpc=None):
    """wrap all functions in a list of views"""

    global views
    def wrapper(func):
        views.append((regex, method, rpc, func))

        def wrapper2(*a, **b):
            return func(*a, **b)
        return wrapper2
    return wrapper

class SmartGit(object):

    def __init__(self, config=None, with_rpc=False):
        self.with_rpc = with_rpc

    def __call__(self, environ, start_response):
        request = Request(environ)
        response = None

        try:
            response = self.handle_request(request)
        except Error as e:
            response = e

        return response(environ, start_response)

    def handle_request(self, request):
        global views
        action = None
        for regex, method, rpc, callable in views:
            if re.match(regex, request.path_info):
                if method != request.method:
                    raise NotAllowed
                action = callable
                break

        if not action:
            raise NotFound()

        return action(self, request)

    @action("(.*?)/git-upload-pack$", "POST", "upload-pack")
    @action("(.*?)/git-receive-pack$", "POST", "receive-pack")
    def service_rpc(self, request):
        if not self.with_rpc:
            raise Forbidden()

        response = Response()
        response.status = 200
        response.content_type = "application/x-git-%s-result" % request.rpc

        command = self.git_command("%s --stateless-rpc %s" % (request.rpc, request.dir))

        with Popen(command, stdin=PIPE, stdout=PIPE) as pipe:
            pipe.stdin.write(request.body)
            while True:
                data = pipe.stdout.read(8192)
                if not data:
                    break
                response.write(data)

        return response


    @action("(.*?)/info/refs$")
    def get_info_refs(self, request):

        service_name = self.get_service_type(request)
        if self.has_access(service_name):
            cmd = git_command("%s --stateless-rpc --advertise-refs ." % service_name)
            refs = Popen(cmd, stdout=PIPE, shell=True)
            refs = refs.stdout.read()

            response = Response()
            response.status = 200
            response.content_type = "application/x-git-%s-advertisement" % service_name
            self.hdr_nocache(response)

            response.write(pkt_write("# service=git-#{service_name}\n"))
            response.write(pkt_flush)
            response.write(refs)

            return response
        else:
            return self.dumb_info_refs(request)

    def dumb_info_refs(self, request):
        self.update_server_info(request)
        return self.send_file(request, "text/plain; charset=utf-8", self.hdr_nocache())

    @action("(.*?)/objects/info/packs$")
    def get_info_packs(self, request):
        return self.send_file(request, "text/plain; charset=utf-8", self.hdr_nocache())

    @action("(.*?)/objects/[0-9a-f]{2}/[0-9a-f]{38}$")
    def get_loose_object(self, request):
        return self.send_file(request, "application/x-git-loose-object", self.hdr_nocache())

    @action("(.*?)/objects/pack/pack-[0-9a-f]{40}\\.pack$")
    def get_pack_file(self, request):
        return self.send_file(request, "application/x-git-packed-objects", self.hdr_cache_forever())
    
    @action("(.*?)/objects/pack/pack-[0-9a-f]{40}\\.idx$")
    def get_idx_file(self, request):
        return self.send_file(request, "application/x-git-packed-objects-toc", self.hdr_cache_forever())

    @action("(.*?)/HEAD$")
    @action("(.*?)/objects/info/alternates$")
    @action("(.*?)/objects/info/http-alternates$")
    @action("(.*?)/objects/info/[^/]*$")
    def get_text_file(self, request):
        return self.send_file(request, "text/plain", self.hdr_cache_forever())

    def send_file(self, request, content_type, response):
        return response

    def get_git_dir(self, path):
        pass

    def get_service_type(self, request):
        pass

    def has_access(self, rpc, check_content_type=False):
        pass

    def git_command(self, command):
        git_bin = self.config.get('git', 'git')
        return  "%s %s" % (git_bin, command)

    def update_server_info(self, request):
        pass

    def hdr_cache_forever(self):
        res = Response()
        res.date = datetime.now().isoformat()
        res.expires = 0
        res.cache_control = "public, max-age=31536000"
        return res

    def hdr_nocache(self):
        res = Response()
        res.expires = "Fri, 01 Jan 1980 00:00:00 GMT"
        res.pragma = "no-cache"
        res.cache_control = "no-cache, max-age=0, must-revalidate"
        return Response()
        

httpd = make_server('localhost', 8051, SmartGit())
httpd.serve_forever()
