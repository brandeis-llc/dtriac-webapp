"""elastic.py

Module with some convenience code for accessing an Elastic Search index.

Based on the module with the same name at ../../elastic.py, which is clearly not
so good.

"""

import re, json
from pprint import pprint
from collections import Counter
from operator import attrgetter

from elasticsearch import Elasticsearch 
from elasticsearch.exceptions import NotFoundError


class Index(object):

    def __init__(self, index_name):
        self.index = index_name
        self.es = Elasticsearch([{'host': 'localhost', 'port': 9200}])

    def get_documents(self):
        query = { "query": { "match_all": {} } }
        return Result(result=self.es.search(index=self.index, body=query, size=500,
                                            _source_includes=['docid', 'title', 'docname']))

    def get(self, doc_id):
        try:
            doc = self.es.get(index=self.index, id=doc_id)
            return doc
        except NotFoundError as e:
            print(e)

    def search(self, query, dribble=False):
        return Result(query_json=query,
                      result=self.es.search(index=self.index, body=query, size=20, scroll="1m"))


class Result(object):

    """Class to wrap an ElasticSearch result."""

    def __init__(self, query_string=None, query_json=None, result=None):
        self.query_string = query_string
        self.query_json = query_json
        self.result = result
        self.hits = [Hit(self, hit) for hit in self.result['hits']['hits']]
        self.total_hits = self._get_total_hits()
        self.sources = [hit.source for hit in self.hits]
        self.scroll_id = result.get('_scroll_id')

    def __str__(self):
        return "&lt;Result %s>" % self.total_hits

    def _get_total_hits(self):
        try:
            # Elastic 7.1.1
            return self.result['hits']['total']['value']
        except TypeError:
            # Elastic 6.4.2
            return self.result['hits']['total']

    def is_tech_query(self):
        bool = self.query_json['query']['bool']
        if len(bool.keys()) == 1:
            matches = list(bool.values())[0]
            if len(matches) == 1:
                pair = matches[0].get('match', matches[0].get('match_phrase'))
                if 'technology' in pair:
                    return pair['technology']
        return False

    def sorted_sources(self):
        self.sources.sort(key = attrgetter('docid'))
        return self.sources

    def write(self):
        fname = "%04d.txt" % nextint()
        with codecs.open(fname, 'w', encoding='utf8') as fh:
            fh.write(json.dumps(self.result, sort_keys=True, indent=4))

    def pp(self):
        print("\n    Number of hits: %d" % self.total_hits)
        for hit in self.hits:
            print("    %s  %.4f  %s" % (hit.docid, hit.score, hit.docname[:80]))

    def print_sources(self, dribble):
        if dribble:
            sources = self.sources
            print('   Got %d hits' % self.total_hits)
            for source in self.sources:
                print('   %s' % source)


class Hit(object):

    def __init__(self, result, hit):
        self.result = result
        self.hit = hit
        self.id = hit['_id']
        self.score = hit['_score']
        self.source = Source(self, hit['_source'])
        self.docid = self.source.source.get('docid')
        self.docname = self.source.source.get('docname')

    def __str__(self):
        return "&lt;Hit %s>" % self.id


class Source(object):

    def __init__(self, hit, source):
        self.hit = hit
        self.source = source
        self.docid = source.get('docid')
        self.docname = source.get('docname')
        self.year = source.get('year')
        self.title = source.get('title')
        self.abstract = source.get('abstract')
        self.text = source.get('text')

    def technologies(self):
        return self.source.get('technology', [])

    def persons(self):
        return self.source.get('person', [])

    def locations(self):
        return self.source.get('location', [])

    def organizations(self):
        return self.source.get('organization', [])

    def technology_links(self):
        return ['<a href="/search?search=true&query=%s">%s</a>' % (tech, tech)
                for tech in self.technologies()]

    def source_size(self):
        return len(self.text)

    def show_fragments(self, query):
        builder = Builder(self, query)
        fragments = []
        for match in builder.matches:
            for offsets in match['offsets'].split():
                p1, p2 = [int(p) for p in offsets.split('-')]
                fragments.append('<' + self.text[p1-50:p2+50].strip() + '>')
        return '\n' +'\n'.join(fragments)

    def get_fragments(self, query):
        builder = Builder(self, query)
        #return builder.parsed_query
        return builder.fragments


class Builder(object):

    def __init__(self, source, query):
        self.source = source
        self.query = query
        self.parsed_query = self._parse_query()
        self.matches = []
        self.fragments = []
        self._set_matches()
        self._set_fragments()

    def _parse_query(self):
        result = []
        for qe in self.query.split():
            field_and_value = tuple(qe.split(':'))
            if len(field_and_value) == 1:
                result.append(('text', field_and_value[0]))
            else:
                result.append(field_and_value)
        return result

    def get_field(self, field):
        return self.source.source.get(field)

    def _set_matches(self):
        """For each field-value pair in the query, check the source for the
        field and see if the value appears in any of the field. For example, if
        we have ('location', 'Italy') we check the list of dictionaries in the
        'location' field of the source. Thos dictionaries ar eof the shape
        {'text': ..., 'offsets': ...} and if we find that the value is included
        in the 'text' field we add the dictionary to the self.matches list."""
        for field, value in self.parsed_query:
            if field == 'text':
                pass
            else:
                for x in self.source.source.get(field, []):
                    if value.lower() in x['text'].lower():
                        self.matches.append(x)

    def _set_fragments(self):
        for match in self.matches:
            for offsets in match['offsets'].split():
                p1, p2 = [int(p) for p in offsets.split('-')]
                self.fragments.append((self.source.text[p1-60:p1],
                                       self.source.text[p1:p2],
                                       self.source.text[p2:p2+60]))
