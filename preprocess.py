import sys
import urllib.request
from bs4 import BeautifulSoup
import os.path
import shutil
import tarfile
import bson
import json
from glob import glob
import re
import shelve
from mpi4py import MPI
from array import array
import time
import socket

class Progress(object):
    def __init__(self, message, total_size):
        self.message = message
        self.total_size = total_size
        self.previous_percent = -1

    def show_progress(self, current_size):
        percent = int(current_size * 100. / self.total_size)
        if percent != self.previous_percent:
            self.print_progress('{:3d}%'.format(percent))
            self.previous_percent = percent

    def print_progress(self, text):
        status = '{} [{}]'.format(self.message, text)
        if MPI.COMM_WORLD.size > 1:
            status = '#{}. {}\n'.format(MPI.COMM_WORLD.rank, status)
        else:
            # Clear previous message and progress
            clear = chr(8) * (len(self.message) + 7)
            if self.previous_percent != -1:
                sys.stdout.write(clear)

        sys.stdout.write(status)
        sys.stdout.flush()

    def finish(self):
        self.print_progress("finished")
        sys.stdout.write('\n')

# class ProgressFile(file, Progress):
#     def __init__(self, *a, **kw):
#         message = kw.pop('message', None)

#         file.__init__(self, *a, **kw)

#         if message is None:
#             message = 'Reading file {}'.format(self.name)

#         Progress.__init__(self, message, os.path.getsize(self.name))

#     def read(self, size):
#         self.show_progress(self.tell())
#         return file.read(self, size)

#     def close(self):
#         if not self.closed:
#             self.finish()
#         file.close(self)

import os
import io

class Progress:
    def __init__(self, message, total_size):
        self.message = message
        self.total_size = total_size
        self.bytes_read = 0

    def show_progress(self, bytes_read):
        self.bytes_read = bytes_read
        # Your progress visualization code here
        print("Progress: {:.2f}%".format(self.bytes_read / self.total_size * 100))

    def finish(self):
        # Any cleanup or finalization code
        pass

class ProgressFile(io.FileIO, Progress):
    def __init__(self, *args, **kwargs):
        message = kwargs.pop('message', None)
        self.total_size = os.path.getsize(args[0])

        io.FileIO.__init__(self, *args, **kwargs)

        if message is None:
            message = 'Reading file {}'.format(args[0])

        Progress.__init__(self, message, self.total_size)

    def read(self, size=-1):
        chunk = io.FileIO.read(self, size)
        self.show_progress(self.tell())
        return chunk

    def close(self):
        if not self.closed:
            self.finish()
        io.FileIO.close(self)


class Preprocessor(object):
    DOWNLOADS_URL = "https://github.com/ghtorrent/ghtorrent.org"
    BSON_FILE_DIR = "dump/github/"

    def __init__(self, process_id, path, *a):
        self.process_id = str(process_id)
        self.dataset = ''
        self.bson_file = ''
        self.path = ''
        self.keep_fields = []

        if path != "" and path[-1] != "/":
            path = path + "/"

        if self.process_id != '':
            self.path = path + self.process_id + '/'

        if self.path != '' and not os.path.exists(self.path):
            os.makedirs(self.path, 0o700)


    def preprocess(self):
        self.get_bson()
        self.convert_bson()

    def get_bson(self):
        if not os.path.isfile(self.path + self.dataset + '.tar.gz'):
            self.download(self.path + self.dataset + '.tar.gz')
        if not os.path.isfile(self.bson_file + '.bson'):
            self.extract()

    def download(self, target):
        message = 'Downloading "{}" dataset'.format(self.dataset)
        self.download_file(self.DOWNLOADS_URL + self.dataset + '.tar.gz', target, message=message)

    def download_file(self, url, target, message=None):
        stream = urllib.request.urlopen(url)
        file = open(target, 'wb')
        file_size = int(stream.info().getheaders('Content-Length')[0])
        downloaded_size = 0
        block_size = 8192

        if message is None:
            message = 'Downloading "{}"'.format(url)

        progress = Progress(message, file_size)

        while True:
            buffer = stream.read(block_size)
            if not buffer:
                break

            downloaded_size += len(buffer)
            file.write(buffer)
            progress.show_progress(downloaded_size)

        progress.finish()
        file.close()

    def extract(self):
        message = 'Untarring "{}" dataset'.format(self.dataset)
        file = ProgressFile(self.path + self.dataset + '.tar.gz', message=message)
        tar = tarfile.open(fileobj=file)
        if self.path != "":
            tar.extractall(self.path)
        else:
            tar.extractall()
        tar.close()
        file.close()

    def convert_bson(self):
        raise NotImplementedError("Cannot call convert_bson on the base class: a subclass must implement this method instead")

    def cleanup(self, output_name=""):
        os.remove(self.bson_file)
        os.removedirs(self.path + self.BSON_FILE_DIR)
        if self.path != "" and output_name != "":
            print('#{}. Moving output file "{}" to shared directory...'.format(MPI.COMM_WORLD.rank, output_name))
            if os.path.exists(output_name):
                os.remove(output_name)
            shutil.move(self.path + output_name, '.')

class Shelf(object):
    @classmethod
    def merge_shelves(cls):
        files = sorted(glob('languages-*.shelf'))
        count = len(files)
        if count == 0:
            return

        message = 'Merging partial shelves'
        progress = Progress(message, count)

        merged = shelve.open('languages.shelf')
        for index in range(count):
            progress.show_progress(index)
            shelf = shelve.open(files[index])
            merged.update(shelf)
            shelf.close()
            os.remove(files[index])
        merged.close()
        progress.finish()

class Commit_Comments_Preprocessor(Preprocessor):
    def __init__(self, process_id, path, date, group, *a):
        super(Commit_Comments_Preprocessor, self).__init__(process_id, path)
        self.dataset = 'commit_comments-dump.' + date
        self.bson_file = self.path + self.BSON_FILE_DIR + 'commit_comments.bson'
        self.group = group
        self.keep_fields = ['id', 'body']
        if group not in self.keep_fields:
            self.keep_fields.append(group)

    def is_latin(self, string):
        try:
            string.encode('ascii')
        except UnicodeEncodeError:
            return False
        
        return True

    def convert_bson(self):
        output = open(self.path + self.dataset + '.json', 'wb')
        message = 'Converting BSON "{}" and filtering fields'.format(self.dataset)
        bson_file = ProgressFile(self.bson_file, 'rb', message=message)
        
        Shelf.merge_shelves()
        
        if os.path.isfile('languages.shelf'):
            if self.path != "" and not os.path.isfile(self.path + 'languages.shelf'):
                print("#{}. Copying languages shelf to local directory...".format(MPI.COMM_WORLD.rank))
                shutil.copy('languages.shelf', self.path)
            languages = shelve.open(self.path + 'languages.shelf', writeback=True)
        else:
            languages = {}
        
        # Read every BSON object as an iterator to save memory.
        for raw_json in bson.decode_file_iter(bson_file):
            if not self.is_latin(raw_json['body']):
                continue

            preprocessed_json = {}
            repository = str(re.search(r"repos/([^/]+/[^/]+)(/|$)", raw_json['url']).group(1))
            raw_json['language'] = ''
            if repository in languages:
                raw_json['language'] = languages[repository]
            for item in self.keep_fields:
                preprocessed_json[item] = raw_json[item]
           
            json.dump(preprocessed_json, output)
            output.write('\n')

        output.close()
        bson_file.close()
        self.cleanup()

class Repos_Preprocessor(Preprocessor):
    def __init__(self, process_id, path, date, *a):
        super(Repos_Preprocessor, self).__init__(process_id, path)
        self.dataset = 'repos-dump.' + date
        self.bson_file = self.path + self.BSON_FILE_DIR + 'repos.bson'

    def convert_bson(self):
        message = 'Converting BSON "{}" to language shelf #{}'.format(self.dataset, self.process_id)
        bson_file = ProgressFile(self.bson_file, 'rb', message=message)
        shelf_name = 'languages-' + self.process_id + '.shelf'
        languages = shelve.open(self.path + shelf_name, writeback=True)

        # Read every BSON object as an iterator to save memory.
        for raw_json in bson.decode_file_iter(bson_file):
            repository = raw_json['full_name'].encode('utf-8')
            language = raw_json['language'].encode('utf-8') if raw_json['language'] is not None else ''
            languages[repository] = language

        languages.close()
        bson_file.close()
        self.cleanup(shelf_name)

class Process(object):
    def __init__(self, path, task, preprocessor, group):
        self.path = path
        self.task = task
        self.preprocessor = preprocessor
        self.group = group

        self.comm = MPI.COMM_WORLD
        self.process_id = self.comm.rank
        self.num_processes = self.comm.size
        # MPI buffer
        self.ready = bytearray(1)  # Replace array('c', '\0') with bytearray(1)

    def execute(self):
        if self.process_id == 0:
            if self.num_processes == 1:
                self.run_sequential()
            else:
                self.run_master()
        else:
            self.run_process()
    
    def run_sequential(self):
        # Fetch the dumps from the GHTorrent website and
        # perform sequentially
        dates = self.get_downloads(self.task + '-dump')
        for tag in range(len(dates)):
            if self.task == "commit_comments":
                if dates[tag]['date'] == '2015-01-29':
                    # We only need the labeled dump when not running MPI
                    preprocessor = self.preprocessor('', self.path, dates[tag]['date'], self.group)
                    preprocessor.preprocess()
                    break
            else:
                preprocessor = self.preprocessor(tag, self.path, dates[tag]['date'], self.group)
                preprocessor.preprocess()

    def run_master(self):
        print('MASTER on node {}'.format(socket.gethostname()))

        if self.task == "commit_comments":
            # Merge any shelves beforehand
            Shelf.merge_shelves()

        # Fetch the dumps from the GHTorrent website and
        # process them in parallel on the other processes.
        # Start with the largest data sets so that we have better balancing
        dates = self.get_downloads(self.task + '-dump')
        dates = sorted(dates, key=lambda v: v['size'], reverse=True)

        print('MASTER: Waiting to distribute {} jobs'.format(len(dates)))
        # Automatically balance the jobs across the processes by sending jobs 
        # to processes that tell us they are free.
        for tag in xrange(len(dates)):
            ready = '\0'
            while ready != '\1':
                (ready, status) = self.wait_ready()

            pid = status.Get_source()

            # A process is ready to receive, so send a job
            print('MASTER: Process {} receives job {}'.format(pid, tag))
            self.comm.send(dates[tag]['date'], dest=pid, tag=tag)

        print('MASTER: Done distributing jobs, starting finish run')
        self.finish_master()
        print('MASTER: Done')

    def finish_master(self):
        # We run another cycle through all the other processes to let them know 
        # they are done.
        for i in xrange(self.num_processes - 1):
            ready = '\0'
            while ready != '\1':
                (ready, status) = self.wait_ready()

            # We are done sending jobs, so tell the process that it is done
            pid = status.Get_source()
            print('MASTER: Process {} is done ({} of {})'.format(pid, i+1, self.num_processes - 1))
            self.comm.send("", dest=pid, tag=i)

    def run_process(self):
        print('PROCESS {} on node {}'.format(self.process_id, socket.gethostname()))

        # Process dumps as jobs that we receive from the master.
        # Keep on running until the master lets us know we are done.
        while True:
            # Let the master know that this process is ready
            self.comm.Send(array('c', '\1'), dest=0, tag=self.process_id)
            print('PROCESS {}: Sent ready message'.format(self.process_id))

            # Execute only the preprocessor for this particular job
            # if it received the signal to run.
            status = MPI.Status()
            date = self.comm.recv(source=0, tag=MPI.ANY_TAG, status=status)
            tag = status.Get_tag()
            if date == "":
                print('PROCESS {}: Done'.format(self.process_id))
                break

            print('PROCESS {}: Received job {} with date {} for preprocessing'.format(self.process_id, tag, date))
            preprocessor = self.preprocessor(tag, self.path, date, self.group)
            preprocessor.preprocess()

    def wait_ready(self):
        # Wait for processes to be ready. We poll a receive of a message from 
        # any process. In order to reduce CPU usage of the idle master, we use 
        # our own sleep loop.
        status = MPI.Status()
        req = self.comm.Irecv(self.ready, source=MPI.ANY_SOURCE, tag=MPI.ANY_TAG)
        while not req.Test(status=status):
            time.sleep(1)

        # Finish the request
        req.Wait()
        return self.ready.tostring(), status

    # def get_downloads(self, prefix):
    #     dates = []
    #     html_page = urllib.request.urlopen(Preprocessor.DOWNLOADS_URL)
    #     soup = BeautifulSoup(html_page, features="html.parser")
    #     for link in soup.findAll('a'):
    #         href = link.get('href')
    #         if href.startswith(prefix):
    #             date = href[len(prefix)+1:-7]
    #             attrs = re.split(r'\s\s+', link.nextSibling)
    #             dates.append({'date': date, 'size': int(attrs[2])})

    #     return dates

    def get_downloads(self, prefix):
        dates = []
        html_page = urllib.request.urlopen(Preprocessor.DOWNLOADS_URL)
        soup = BeautifulSoup(html_page, features="html.parser")
        for link in soup.findAll('a'):
            href = link.get('href')
            if href is not None and href.startswith(prefix):
                date = href[len(prefix)+1:-7]
                attrs = re.split(r'\s\s+', link.nextSibling)
                dates.append({'date': date, 'size': int(attrs[2])})

        return dates


def main(argv):
    task = argv[0] if len(argv) > 0 else "commit_comments"
    group = argv[1] if len(argv) > 1 else "id"
    path = argv[2] if len(argv) > 2 else ""

    # Buffers of MPI
    date = ""
    ready = bytearray(1)

    preprocessors = {
        "repos": Repos_Preprocessor,
        "commit_comments": Commit_Comments_Preprocessor
    }

    if task in preprocessors:
        if task == "repos" and group == "language" and os.path.isfile('languages.shelf'):
            print('Nothing to be done for task {}, group {}.'.format(task, group))
        else:
            process = Process(path, task, preprocessors[task], group)
            process.execute()
    else:
        print("Unrecognized value for 'task': '{}'".format(task))
        print("Must be one of {}".format(', '.join(preprocessors.keys())))
        print("Usage: [mpiexec -n <num_processes>] python preprocess.py <task> [group]")

if __name__ == "__main__":
    main(sys.argv[1:])
