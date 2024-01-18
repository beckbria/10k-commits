from dataclasses import dataclass
import os
import re
import sys
import zlib

# This is a partial parser for the Git repository format for working on the MIT Mystery Hunt 2024
# puzzle "The 10,000 commit repository"

# Oh no! I, Ben Bitdiddle, have dropped my repo and now all the commits are out of order! 
# Please help me put it back to how it was. Careful, though - leave everything except the 
# order the same! (This includes the file contents, author, author date, committer, commit 
# date, and commit message. This is my work, not yours.)

# The very first commit I made had the hash 6ff5175133e7ed5b329e5c47c7f7bb4236ecd0ac. 
# The last one... well, it ended with efb954, but I don't remember how it started.

# TODO: Neither of those commits appears in this repository. Figure out what that means...

# Setup: First unpack the repository into a new git repository
# $ mkdir ../10k && cd ../10k
# $ git unpack-objects < ../the-10000-commit-git-repo/.git/objects/pack/pack-85e21b7c45fb83f65acf4a601db6d1dd1ed0af83.pack
# Then run this tool in that new repository with the unpacked object files

# Git directory path
objdir = "./.git/objects"
ignore_dirs = ("info","pack")

@dataclass
class GitCommit:
    """Represents data associated with a Git Commit."""
    num: int
    tree_id: str
    parent_id: str
    author: str
    author_time: int
    committer: str
    commit_time: int

@dataclass
class GitBlob:
    """Represents data associated with a Git Blob."""
    num: int
    commit_order: int

@dataclass
class GitTree:
    """Represents data associated witha Git Tree."""
    num: int
    data: str
    binary_data: bytes

    def blobId(self):
        """Extracts the hex string representing the blob hash."""
        return self.binary_data[-20:].hex()

    
@dataclass
class Commit:
    """Represents data associated with a single commit in the 10k commits repo"""
    hash: str
    order: int
    original_parent_hash: str
    original_parent_order: int
    author_time: int
    commit_time: int

    @staticmethod
    def tablePrefix():
        return "Hash\tOrder\tParent\tParentOrder\tAuthorTime\tCommitTime"

    def __str__(self): 
        return "%s\t%s\t%s\t%s\t%s\t%s" % (self.hash, str(self.order), self.original_parent_hash, str(self.original_parent_order), self.author_time, self.commit_time)

class GitParser:
    """Parses the objects from a git repository"""

    # Regex parsing constants
    _separator = "\\\\x00"
    _newline = "\\\\n"
    _capture_number = "([0-9]+)"
    _capture_hash = "([0-9a-f]+)"
    _capture_time = "<> " + _capture_number + " \\+0000"
    _capture_name = " ([A-Za-z ]+) "

    # We're looking for three formats:
    # Blob: b'blob 40\x00This is the README in the 1929th commit.'
    _blob_re = re.compile("^blob " + _capture_number + _separator + "This is the README in the " + _capture_number + "\\w\\w commit.$")
    # Commit: b'commit 187\x00tree 62448925a5155a35cddd9501599f9372c74307c0\nparent b988091bfb4fc8fefe6c16ef73e8436fb2bda680\nauthor Ben Bitdiddle <> 1366331681 +0000\ncommitter Ben Bitdiddle <> 1366331681 +0000\n\ncommit\n'
    _prefix = "^commit " + _capture_number + _separator
    _tree_capture = "tree " + _capture_hash + _newline
    _parent_capture = "(parent " + _capture_hash + _newline + ")?" # Parent is optional
    _author_capture = "author" + _capture_name + _capture_time + _newline
    _committer_capture = "committer" + _capture_name + _capture_time
    _suffix = _newline + _newline + "commit" + _newline + "$"
    _commit_re = re.compile(_prefix + _tree_capture + _parent_capture + _author_capture + _committer_capture + _suffix)
    # Tree: 
    # b'tree 38\x00100644 README.txt\x00\xfb\x1c"}W+\x96-\xcb\xe4\x13\x1e\xa3t\xaa\xcb\xa9\xff\xe6G'
    _tree_re = re.compile("^.*tree ([0-9]+)" + _separator + "100644 README\\.txt(.*)$")

    def __init__(self):
        self.blobs = {}
        self.trees = {}
        self.commits = {}

    def blobForCommit(self, hash):
        commit = self.commits[hash]
        tree = self.trees[commit.tree_id]
        blob_id = tree.blobId()
        if blob_id not in self.blobs:
            # This can be a short ID.  There should be exactly one blob with this prefix
            full_id = blob_id
            for b in self.blobs:
                if b.startswith(blob_id):
                    if full_id != blob_id:
                        print("ERROR: Got ambiguous short blob ID ", blob_id, " not found (ref. commit ", hash, " - tree ", commit.tree_id, ") which matches ", full_id, " and ", b)
                    full_id = b
            
            blob_id = full_id
            if blob_id not in self.blobs:
                print("ERROR: Blob ", blob_id, " not found (ref. commit ", hash, " - tree ", commit.tree_id, ")")
        return self.blobs[blob_id]

    def parseObject(self, hash, contents):
        contentsStr = str(contents)
        if not (contentsStr.startswith("b'") or contentsStr.startswith('b"')):
            print("*** UNKNOWN FILE: ", hash, " *** ", contentsStr)
            return
        # Remove the binary prefix and suffix
        contentsStr = contentsStr[2:-1]

        if match := GitParser._blob_re.search(contentsStr):
            self.blobs[hash] = GitBlob(num=match.group(1), commit_order=match.group(2))
        elif match := GitParser._commit_re.search(contentsStr):
            self.commits[hash] = GitCommit(num=match.group(1), tree_id=match.group(2), parent_id=match.group(4), author=match.group(5), author_time=match.group(6), committer=match.group(7), commit_time=match.group(8))
        elif match := GitParser._tree_re.search(contentsStr):
            self.trees[hash] = GitTree(num=match.group(1), data=match.group(2), binary_data=contents)
        else:
            print("*** UNKNOWN FILE: ", hash, " *** ", contentsStr)

    def orderedCommits(self):
        ordered_commits = list(map(lambda c : self._buildOrderedCommit(c), self.commits))
        ordered_commits.sort(key=lambda commit: commit.order)
        return ordered_commits
    
    def _buildOrderedCommit(self, commit_id):
        commit_data = self.commits[commit_id]
        if commit_data.parent_id is not None and commit_data.parent_id not in self.commits:
            print("Commit ", commit_id, " has unknown parent ", commit_data.parent_id)
        if commit_data.tree_id not in self.trees:
            print("Commit ", commit_id, " has unknown tree ", commit_data.tree_id)

        # Gather relevant data
        blob = self.blobForCommit(commit_id)
        original_parent_order = None
        if commit_data.parent_id is not None:
            parent_blob = self.blobForCommit(commit_data.parent_id)
            original_parent_order = parent_blob.commit_order
        return Commit(hash=commit_id, order=int(blob.commit_order), original_parent_hash=commit_data.parent_id, original_parent_order=original_parent_order, author_time=commit_data.author_time, commit_time=commit_data.commit_time)


# Read all of the object files in the repository
parser = GitParser()
dirs = os.listdir(objdir)
for d in dirs:
    if d in ignore_dirs:
        continue
    prefix = str(d)
    dir = os.path.join(objdir, d)
    for commit in os.listdir(dir):
        hash = prefix + str(commit)
        contents = ""
        with open(os.path.join(dir, commit), mode='rb') as file:
            contents = file.read()
        contents = zlib.decompress(contents)
        parser.parseObject(hash=hash, contents=contents)

print("Total blobs ", len(parser.blobs), " -- total trees ", len(parser.trees), " -- total commits ", len(parser.commits))
print(Commit.tablePrefix())
for c in parser.orderedCommits():
    print(c)
