"""RCV1 dataset.
"""

# Author: Tom Dupre la Tour
# License: BSD 3 clause

import logging

from os.path import exists, join
from gzip import GzipFile
from io import BytesIO
from contextlib import closing

try:
    from urllib2 import urlopen
except ImportError:
    from urllib.request import urlopen

import numpy as np
import scipy.sparse as sp

from .base import get_data_home
from .base import Bunch
from ..utils.fixes import makedirs
from ..externals import joblib
from .svmlight_format import load_svmlight_files
from ..utils import shuffle as shuffle_


URL = ('http://jmlr.csail.mit.edu/papers/volume5/lewis04a/'
       'a13-vector-files/lyrl2004_vectors')
URL_topics = ('http://jmlr.csail.mit.edu/papers/volume5/lewis04a/'
              'a08-topic-qrels/rcv1-v2.topics.qrels.gz')

logger = logging.getLogger()


def fetch_rcv1(data_home=None, download_if_missing=True,
               random_state=None, shuffle=False):
    """Load the RCV1 multilabel dataset, downloading it if necessary.

    Version: RCV1-v2, vectors, full sets, topics multilabels.

    ==============     =====================
    Classes                              103
    Samples total                     804414
    Dimensionality                     47236
    Features           real, between 0 and 1
    ==============     =====================

    Read more in the :ref:`User Guide <datasets>`.

    Parameters
    ----------
    data_home : string, optional
        Specify another download and cache folder for the datasets. By default
        all scikit learn data is stored in '~/scikit_learn_data' subfolders.

    download_if_missing : boolean, default=True
        If False, raise a IOError if the data is not locally available
        instead of trying to download the data from the source site.

    random_state : int, RandomState instance or None, optional (default=None)
        Random state for shuffling the dataset.
        If int, random_state is the seed used by the random number generator;
        If RandomState instance, random_state is the random number generator;
        If None, the random number generator is the RandomState instance used
        by `np.random`.

    shuffle : bool, default=False
        Whether to shuffle dataset.

    Returns
    -------
    dataset : dict-like object with the following attributes:

    dataset.data : scipy csr array, shape (804414, 47236)
        The first 23149 samples are training samples.
        The last 781265 samples are testing samples.
        The array has 0.16% of non zero values.

    dataset.target : scipy csr array, shape (804414, 103)
        Each sample has a value of 1 in its categories, and 0 in others.
        The array has 3.15% of non zero values.

    dataset.sample_id : numpy array, shape (804414,)
        Identification number of each sample, as ordered in dataset.data.

    dataset.target_names : numpy array of object, length (103)
        Names of each target (RCV1 topics), as ordered in dataset.target.

    dataset.DESCR : string
        Description of the RCV1 dataset.

    """
    N_SAMPLES = 804414
    N_FEATURES = 47236
    N_CATEGORIES = 103

    data_home = get_data_home(data_home=data_home)
    rcv1_dir = join(data_home, "RCV1")
    if download_if_missing:
        makedirs(rcv1_dir, exist_ok=True)

    samples_path = join(rcv1_dir, "samples.pkl")
    sample_id_path = join(rcv1_dir, "sample_id.pkl")
    sample_topics_path = join(rcv1_dir, "sample_topics.pkl")
    topics_path = join(rcv1_dir, "topics_names.pkl")

    # load data (X) and sample_id
    if download_if_missing and (not exists(samples_path) or
                                not exists(sample_id_path)):
        file_urls = ["%s_test_pt%d.dat.gz" % (URL, i) for i in range(4)]
        file_urls.append("%s_train.dat.gz" % URL)
        files = []
        for file_url in file_urls:
            logger.warning("Downloading %s" % file_url)
            with closing(urlopen(file_url)) as online_file:
                # buffer the full file in memory to make possible to Gzip to
                # work correctly
                f = BytesIO(online_file.read())
            files.append(GzipFile(fileobj=f))

        Xy = load_svmlight_files(files, n_features=N_FEATURES)

        # Training data is before testing data
        X = sp.vstack([Xy[8], Xy[0], Xy[2], Xy[4], Xy[6]]).tocsr()
        sample_id = np.hstack((Xy[9], Xy[1], Xy[3], Xy[5], Xy[7]))
        sample_id = sample_id.astype(np.int32)

        joblib.dump(X, samples_path, compress=9)
        joblib.dump(sample_id, sample_id_path, compress=9)

    else:
        X = joblib.load(samples_path)
        sample_id = joblib.load(sample_id_path)

    # load target (y), categories, and sample_id_bis
    if download_if_missing and (not exists(sample_topics_path) or
                                not exists(topics_path)):
        logger.warning("Downloading %s" % URL_topics)
        with closing(urlopen(URL_topics)) as online_topics:
            f = BytesIO(online_topics.read())

        # parse the target file
        n_cat = -1
        n_doc = -1
        doc_previous = -1
        y = np.zeros((N_SAMPLES, N_CATEGORIES), dtype=np.int8)
        sample_id_bis = np.zeros(N_SAMPLES, dtype=np.int32)
        category_names = {}
        for line in GzipFile(fileobj=f, mode='rb'):
            line_components = line.decode("ascii").split(u" ")
            if len(line_components) == 3:
                cat, doc, _ = line_components
                if cat not in category_names:
                    n_cat += 1
                    category_names[cat] = n_cat

                doc = int(doc)
                if doc != doc_previous:
                    doc_previous = doc
                    n_doc += 1
                    sample_id_bis[n_doc] = doc
                y[n_doc, category_names[cat]] = 1

        # Samples in X are ordered with sample_id,
        # whereas in y, they are ordered with sample_id_bis.
        permutation = _find_permutation(sample_id_bis, sample_id)
        y = sp.csr_matrix(y[permutation, :])

        # save category names in a list, with same order than y
        categories = np.empty(N_CATEGORIES, dtype=object)
        for k in category_names.keys():
            categories[category_names[k]] = k

        joblib.dump(y, sample_topics_path, compress=9)
        joblib.dump(categories, topics_path, compress=9)

    else:
        y = joblib.load(sample_topics_path)
        categories = joblib.load(topics_path)

    if shuffle:
        X, y, sample_id = shuffle_(X, y, sample_id, random_state=random_state)

    return Bunch(data=X, target=y, sample_id=sample_id,
                 target_names=categories, DESCR=__doc__)


def _inverse_permutation(p):
    """inverse permutation p"""
    n = p.size
    s = np.zeros(n, dtype=np.int32)
    i = np.arange(n, dtype=np.int32)
    np.put(s, p, i)  # s[p] = i
    return s


def _find_permutation(a, b):
    """find the permutation from a to b"""
    t = np.argsort(a)
    u = np.argsort(b)
    u_ = _inverse_permutation(u)
    return t[u_]
