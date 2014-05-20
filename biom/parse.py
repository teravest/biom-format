#!/usr/bin/env python

# ----------------------------------------------------------------------------
# Copyright (c) 2011-2013, The BIOM Format Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
# ----------------------------------------------------------------------------

from __future__ import division
from string import maketrans
import numpy as np
from biom import __version__
from biom.exception import BiomParseException, UnknownAxisError
from biom.table import Table
import json

__author__ = "Justin Kuczynski"
__copyright__ = "Copyright 2011-2013, The BIOM Format Development Team"
__credits__ = ["Justin Kuczynski", "Daniel McDonald", "Greg Caporaso",
               "Jose Carlos Clemente Litran", "Adam Robbins-Pianka",
               "Jose Antonio Navas Molina"]
__license__ = "BSD"
__url__ = "http://biom-format.org"
__maintainer__ = "Daniel McDonald"
__email__ = "daniel.mcdonald@colorado.edu"

MATRIX_ELEMENT_TYPE = {'int': int, 'float': float, 'unicode': unicode,
                       u'int': int, u'float': float, u'unicode': unicode}

QUOTE = '"'
JSON_OPEN = set(["[", "{"])
JSON_CLOSE = set(["]", "}"])
JSON_SKIP = set([" ", "\t", "\n", ","])
JSON_START = set(
    ["0",
     "1",
     "2",
     "3",
     "4",
     "5",
     "6",
     "7",
     "8",
     "9",
     "{",
     "[",
     '"'])


def direct_parse_key(biom_str, key):
    """Returns key:value from the biom string, or ""

    This method pulls an arbitrary key/value pair out from a BIOM string
    """
    base_idx = biom_str.find('"%s":' % key)
    if base_idx == -1:
        return ""
    else:
        start_idx = base_idx + len(key) + 3  # shift over "key":

    # find the start token
    cur_idx = start_idx
    while biom_str[cur_idx] not in JSON_START:
        cur_idx += 1

    if biom_str[cur_idx] not in JSON_OPEN:
        # do we have a number?
        while biom_str[cur_idx] not in [",", "{", "}"]:
            cur_idx += 1

    else:
        # we have an object
        stack = [biom_str[cur_idx]]
        cur_idx += 1
        while stack:
            cur_char = biom_str[cur_idx]

            if cur_char == QUOTE:
                if stack[-1] == QUOTE:
                    stack.pop()
                else:
                    stack.append(cur_char)
            elif cur_char in JSON_CLOSE:
                try:
                    stack.pop()
                except IndexError:  # got an int or float?
                    cur_idx -= 1
                    break
            elif cur_char in JSON_OPEN:
                stack.append(cur_char)
            cur_idx += 1

    return biom_str[base_idx:cur_idx]


def direct_slice_data(biom_str, to_keep, axis):
    """Pull out specific slices from a BIOM string

    biom_str : JSON-formatted BIOM string
    to_keep  : indices to keep
    axis     : either 'samples' or 'observations'

    Will raise IndexError if the inices are out of bounds. Fully zerod rows
    or columns are possible and this is _not_ checked.
    """
    if axis not in ['observation', 'sample']:
        raise IndexError("Unknown axis type")

    # it would be nice if all of these lookups could be done in a single
    # traversal of biom_str, but it likely is at the cost of code complexity
    shape_kv_pair = direct_parse_key(biom_str, "shape")
    if shape_kv_pair == "":
        raise ValueError("biom_str does not appear to be in BIOM format!")

    data_fields = direct_parse_key(biom_str, "data")
    if data_fields == "":
        raise ValueError("biom_str does not appear to be in BIOM format!")

    matrix_type_kv_pair = direct_parse_key(biom_str, "matrix_type")
    if matrix_type_kv_pair == "":
        raise ValueError("biom_str does not appear to be in BIOM format!")

    # determine shape
    raw_shape = shape_kv_pair.split(':')[-1].replace("[", "").replace("]", "")
    n_rows, n_cols = map(int, raw_shape.split(","))

    # slice to just data
    data_start = data_fields.find('[') + 1
    # trim trailing ]
    data_fields = data_fields[data_start:len(data_fields) - 1]

    # bounds check
    if min(to_keep) < 0:
        raise IndexError("Observations to keep are out of bounds!")

    # more bounds check and set new shape
    new_shape = "[%d, %d]"
    if axis == 'observation':
        if max(to_keep) >= n_rows:
            raise IndexError("Observations to keep are out of bounds!")
        new_shape = new_shape % (len(to_keep), n_cols)
    elif axis == 'sample':
        if max(to_keep) >= n_cols:
            raise IndexError("Samples to keep are out of bounds!")
        new_shape = new_shape % (n_rows, len(to_keep))

    to_keep = set(to_keep)
    new_data = []

    if axis == 'observation':
        new_data = _direct_slice_data_sparse_obs(data_fields, to_keep)
    elif axis == 'sample':
        new_data = _direct_slice_data_sparse_samp(data_fields, to_keep)

    return '"data": %s, "shape": %s' % (new_data, new_shape)

STRIP_F = lambda x: x.strip("[] \n\t")


def _remap_axis_sparse_obs(rcv, lookup):
    """Remap a sparse observation axis"""
    row, col, value = map(STRIP_F, rcv.split(','))
    return "%s,%s,%s" % (lookup[row], col, value)


def _remap_axis_sparse_samp(rcv, lookup):
    """Remap a sparse sample axis"""
    row, col, value = map(STRIP_F, rcv.split(','))
    return "%s,%s,%s" % (row, lookup[col], value)


def _direct_slice_data_sparse_obs(data, to_keep):
    """slice observations from data

    data : raw data string from a biom file
    to_keep : rows to keep
    """
    # interogate all the datas
    new_data = []
    remap_lookup = dict([(str(v), i) for i, v in enumerate(sorted(to_keep))])
    for rcv in data.split('],'):
        r, c, v = STRIP_F(rcv).split(',')
        if r in remap_lookup:
            new_data.append(_remap_axis_sparse_obs(rcv, remap_lookup))
    return '[[%s]]' % '],['.join(new_data)


def _direct_slice_data_sparse_samp(data, to_keep):
    """slice samples from data

    data : raw data string from a biom file
    to_keep : columns to keep
    """
    # could do sparse obs/samp in one forloop, but then theres the
    # expense of the additional if-statement in the loop
    new_data = []
    remap_lookup = dict([(str(v), i) for i, v in enumerate(sorted(to_keep))])
    for rcv in data.split('],'):
        r, c, v = rcv.split(',')
        if c in remap_lookup:
            new_data.append(_remap_axis_sparse_samp(rcv, remap_lookup))
    return '[[%s]]' % '],['.join(new_data)


def get_axis_indices(biom_str, to_keep, axis):
    """Returns the indices for the associated ids to keep

    biom_str : a BIOM formatted JSON string
    to_keep  : a list of IDs to get indices for
    axis     : either 'samples' or 'observations'

    Raises KeyError if unknown key is specified
    """
    to_keep = set(to_keep)
    if axis == 'observation':
        axis_key = 'rows'
        axis_data = direct_parse_key(biom_str, axis_key)
    elif axis == "sample":
        axis_key = 'columns'
        axis_data = direct_parse_key(biom_str, axis_key)
    else:
        raise ValueError("Unknown axis!")

    if axis_data == "":
        raise ValueError("biom_str does not appear to be in BIOM format!")

    axis_data = json.loads("{%s}" % axis_data)

    all_ids = set([v['id'] for v in axis_data[axis_key]])
    if not to_keep.issubset(all_ids):
        raise KeyError("Not all of the to_keep ids are in biom_str!")

    idxs = [i for i, v in enumerate(axis_data[axis_key]) if v['id'] in to_keep]
    idxs_lookup = set(idxs)

    subset = {axis_key: []}
    for i, v in enumerate(axis_data[axis_key]):
        if i in idxs_lookup:
            subset[axis_key].append(v)

    return idxs, json.dumps(subset)[1:-1]  # trim off { and }


def parse_biom_table(fp, ids=None, axis='sample', input_is_dense=False):
    r"""Parses the biom table stored in the filepath `fp`

    Parameters
    ----------
    fp : file like
        File alike object storing the BIOM table
    ids : iterable
        The sample/observation ids of the samples/observations that we need
        to retrieve from the biom table
    axis : {'sample', 'observation'}, optional
        The axis to subset on
    input_is_dense : boolean
        Indicates if the BIOM table is dense or sparse. Valid only for JSON
        tables.

    Returns
    -------
    Table
        The BIOM table stored at fp

    Raises
    ------
    ValueError
        If `samples` and `observations` are provided.

    Notes
    -----
    Subsetting from the BIOM table is only supported in one axis

    Examples
    --------
    Parse a hdf5 biom table

    >>> from h5py import File # doctest: +SKIP
    >>> from biom.parse import parse_biom_table
    >>> f = File('rich_sparse_otu_table_hdf5.biom') # doctest: +SKIP
    >>> t = parse_biom_table(f) # doctest: +SKIP

    Parse a hdf5 biom table subsetting observations
    >>> from h5py import File # doctest: +SKIP
    >>> from biom.parse import parse_biom_table
    >>> f = File('rich_sparse_otu_table_hdf5.biom') # doctest: +SKIP
    >>> t = parse_biom_table(f, ids=["GG_OTU_1"],
    ...                      axis='observation') # doctest: +SKIP
    """
    if axis not in ['observation', 'sample']:
        UnknownAxisError(axis)

    try:
        return Table.from_hdf5(fp, ids=ids, axis=axis)
    except:
        pass

    if hasattr(fp, 'read'):
        old_pos = fp.tell()
        try:
            t = Table.from_json(json.load(fp), input_is_dense=input_is_dense)
        except ValueError:
            fp.seek(old_pos)
            t = Table.from_tsv(fp, None, None, lambda x: x)
    elif isinstance(fp, list):
        try:
            t = Table.from_json(json.loads(''.join(fp)),
                                input_is_dense=input_is_dense)
        except ValueError:
            t = Table.from_tsv(fp, None, None, lambda x: x)
    else:
        t = Table.from_json(json.loads(fp), input_is_dense=input_is_dense)

    if ids is not None:
        f = lambda data, id_, md: id_ in ids
        t.filter(f, axis=axis)
        axis = 'observation' if axis == 'sample' else 'sample'
        f = lambda vals, id_, md: np.any(vals)
        t.filter(f, axis=axis)

    return t


def sc_pipe_separated(x):
    complex_metadata = []
    for y in x.split('|'):
        simple_metadata = []
        for e in y.split(';'):
            simple_metadata.append(e.strip())
        complex_metadata.append(simple_metadata)
    return complex_metadata


class MetadataMap(dict):

    @classmethod
    def from_file(cls, lines, strip_quotes=True, suppress_stripping=False,
                  header=None, process_fns=None):
        """Parse mapping file that relates samples or observations to metadata.

        Format: header line with fields
                optionally other comment lines starting with #
                tab-delimited fields

        process_fns: a dictionary of functions to apply to metadata categories.
         the keys should be the column headings, and the values should be
         functions which take a single value. For example, if the values in a
         column called "taxonomy" should be split on semi-colons before being
         added as metadata, and all other columns should be left as-is,
         process_fns should be:
          {'taxonomy': lambda x: x.split(';')}

        Assumes the first column in the mapping file is the id.

        This method is ported from QIIME (http://www.qiime.org), previously
        named parse_mapping_file/parse_mapping_file_to_dict. QIIME is a GPL
        project, but we obtained permission from the authors of this method
        to port it to the BIOM Format project (and keep it under BIOM's BSD
        license).
        """
        if hasattr(lines, "upper"):
            # Try opening if a string was passed
            try:
                lines = open(lines, 'U')
            except IOError:
                raise BiomParseException("A string was passed that doesn't "
                                         "refer to an accessible filepath.")

        if strip_quotes:
            if suppress_stripping:
                # remove quotes but not spaces
                strip_f = lambda x: x.replace('"', '')
            else:
                # remove quotes and spaces
                strip_f = lambda x: x.replace('"', '').strip()
        else:
            if suppress_stripping:
                # don't remove quotes or spaces
                strip_f = lambda x: x
            else:
                # remove spaces but not quotes
                strip_f = lambda x: x.strip()

        # if the user didn't provide process functions, initialize as
        # an empty dict
        if process_fns is None:
            process_fns = {}

        # Create lists to store the results
        mapping_data = []
        header = header or []
        comments = []

        # Begin iterating over lines
        for line in lines:
            line = strip_f(line)
            if not line or (suppress_stripping and not line.strip()):
                # skip blank lines when not stripping lines
                continue

            if line.startswith('#'):
                line = line[1:]
                if not header:
                    header = line.strip().split('\t')
                else:
                    comments.append(line)
            else:
                # Will add empty string to empty fields
                tmp_line = map(strip_f, line.split('\t'))
                if len(tmp_line) < len(header):
                    tmp_line.extend([''] * (len(header) - len(tmp_line)))
                mapping_data.append(tmp_line)

        if not header:
            raise BiomParseException("No header line was found in mapping "
                                     "file.")
        if not mapping_data:
            raise BiomParseException("No data found in mapping file.")

        first_col = [i[0] for i in mapping_data]
        if len(first_col) != len(set(first_col)):
            raise BiomParseException("First column values are not unique! "
                                     "Cannot be ids.")

        mapping = {}
        for vals in mapping_data:
            current_d = {}
            for k, v in zip(header[1:], vals[1:]):
                try:
                    current_d[k] = process_fns[k](v)
                except KeyError:
                    current_d[k] = v
            mapping[vals[0]] = current_d

        return cls(mapping)

    def __init__(self, mapping):
        """Accepts dictionary mapping IDs to metadata.

        ``mapping`` should be a dictionary mapping an ID to a dictionary of
        metadata. For example:

        {'Sample1': {'Treatment': 'Fast'}, 'Sample2': {'Treatment': 'Control'}}
        """
        super(MetadataMap, self).__init__(mapping)


def generatedby():
    """Returns a generated by string"""
    return 'BIOM-Format %s' % __version__


def convert_table_to_biom(table_f, sample_mapping, obs_mapping,
                          process_func, **kwargs):
    """Convert a contigency table to a biom table

    sample_mapping : dict of {'sample_id':metadata} or None
    obs_mapping : dict of {'obs_id':metadata} or None
    process_func: a function to transform observation metadata
    dtype : type of table data
    """
    otu_table = Table.from_tsv(table_f, obs_mapping, sample_mapping,
                               process_func, **kwargs)
    return otu_table.to_json(generatedby())


def biom_meta_to_string(metadata, replace_str=':'):
    """Determine which format the metadata is and then convert to a string"""

    # Note that since ';' and '|' are used as seperators we must replace them
    # if they exist

    # metadata is just a string (not a list)
    if isinstance(metadata, str) or isinstance(metadata, unicode):
        return metadata.replace(';', replace_str)
    elif isinstance(metadata, list):
        transtab = maketrans(';|', ''.join([replace_str, replace_str]))
        # metadata is list of lists
        if isinstance(metadata[0], list):
            new_metadata = []
            for x in metadata:
                # replace erroneus delimiters
                values = [y.strip().trans(transtab) for y in x]
                new_metadata.append("; ".join(values))
            return "|".join(new_metadata)

        # metadata is list (of strings)
        else:
            return (
                "; ".join(x.replace(';', replace_str).strip()
                          for x in metadata)
            )


def convert_biom_to_table(biom_f, header_key=None, header_value=None,
                          md_format=None):
    """Convert a biom table to a contigency table"""
    table = parse_biom_table(biom_f)
    if md_format is None:
        md_format = biom_meta_to_string

    if table.observation_metadata is None:
        return table.delimited_self()

    if header_key in table.observation_metadata[0]:
        return table.delimited_self(header_key=header_key,
                                    header_value=header_value,
                                    metadata_formatter=md_format)
    else:
        return table.delimited_self()
