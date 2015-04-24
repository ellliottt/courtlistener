import os
import sys

execfile('/etc/courtlistener')
sys.path.append(INSTALL_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "alert.settings")

from juriscraper.lib.string_utils import clean_string, harmonize, titlecase
from juriscraper.lib.date_utils import parse_dates
import pickle
import random
import re
import subprocess
import traceback
from django.utils.timezone import now
from django import db
from alert.citations.find_citations import get_citations
from datetime import datetime, timedelta
from alert.corpus_importer.court_regexes import fd_pairs, state_pairs, \
    disambiguate_by_judge, fb_pairs
from alert.corpus_importer.dup_helpers import get_html_from_raw_text
from alert.corpus_importer.lawbox.judge_extractor import get_judge_from_str
from alert.corpus_importer import dup_finder, dup_helpers
from alert.lib.string_utils import anonymize
from alert.lib.import_lib import map_citations_to_models
from reporters_db import EDITIONS, REPORTERS

import argparse
import datetime
import fnmatch
import hashlib
from lxml.html import tostring
from lxml import html
from alert.search.models import Document, Citation, Court, save_doc_and_cite, Docket


DEBUG = [
    'judge',
    'citations',
    'case_name',
    #'date',
    'docket_number',
    'court',
    #'input_citations',
    #'input_dates',
    #'input_docket_number',
    'input_court',
    'input_case_names',
    #'log_bad_citations',
    #'log_bad_courts',
    #'log_judge_disambiguations',
    #'log_bad_dates',
    #'log_bad_docket_numbers',
    #'log_bad_judges',
    'log_multimerge',
    'counter',
]

try:
    with open('lawbox_fix_file.pkl', 'rb') as fix_file:
        fixes = pickle.load(fix_file)
except (IOError, EOFError):
    fixes = {}

try:
    # Load up SCOTUS dates
    scotus_dates = {}
    with open(os.path.join(INSTALL_ROOT, 'alert', 'corpus_importer', 'scotus_dates.csv'), 'r') as scotus_date_file:
        for line in scotus_date_file:
            citation, date_filed = [line.strip() for line in line.split('|')]
            date_filed = datetime.datetime.strptime(date_filed, '%Y-%m-%d')
            try:
                # If we get fail to get a KeyError, we append to the list we got back, else, we create such a list.
                scotus_dates[citation].append(date_filed)
            except KeyError:
                scotus_dates[citation] = [date_filed]
except IOError:
    print "Unable to load scotus data! Exiting."
    sys.exit(1)

all_courts = Court.objects.all()


def add_fix(case_path, fix_dict):
    """Adds a fix to the fix dictionary. This dictionary looks like:

    fixes = {
        'path/to/some/case.html': {'docket_number': None, 'date_filed': date(1982, 6, 9)},
    }
    """
    if case_path in fixes:
        fixes[case_path].update(fix_dict)
    else:
        fixes[case_path] = fix_dict


def log_print(msg):
    print msg
    log_location = '/sata/lawbox/import_log.txt'
    try:
        with open(log_location, 'a') as log:
            log.write(msg.encode('utf-8') + '\n')
    except IOError:
        # If the log doesn't exist
        print "WARNING: Unable to find log at %s" % log_location


def get_dates(datestr):
    """
    Analyze date string and return date filed, date argued, and date reargument denied
    """
    
    # Get a reasonable date range based on reporters in the citations.    
    start = datetime(1920,1,1)
    end = datetime(2014,12,31)

    dates = []
    for e in clean_html_tree.xpath(path):
        text = tostring(e, method='text', encoding='unicode')
        # Items like "February 4, 1991, at 9:05 A.M." stump the lexer in the date parser. Consequently, we purge
        # the word at, and anything after it.
        text = re.sub(' at .*', '', text)

        # The parser recognizes numbers like 121118 as a date. This corpus does not have dates in that format.
        text = re.sub('\d{5,}', '', text)

        # The parser can't handle 'Sept.' so we tweak it.
        text = text.replace('Sept.', 'Sep.')

        # The parser recognizes dates like December 3, 4, 1908 as 2004-12-3 19:08.
        re_match = re.search('\d{1,2}, \d{1,2}, \d{4}', text)
        if re_match:
            # These are always date argued, thus continue.
            continue

        # The parser recognizes dates like October 12-13, 1948 as 2013-10-12, not as 1948-10-12
        # See: https://www.courtlistener.com/scotus/9ANY/grand-river-dam-authority-v-grand-hydro/
        re_match = re.search('\d{1,2}-\d{1,2}, \d{4}', text)
        if re_match:
            # These are always date argued, thus continue.
            continue

        # Sometimes there's a string like: "Review Denied July 26, 2006. Skip this.
        if 'denied' in text.lower():
            continue

        try:
            if range_dates:
                found = parse_dates.parse_dates(text, sane_start=start, sane_end=end)
            else:
                found = parse_dates.parse_dates(text, sane_end=now())
            if found:
                dates.extend(found)
        except UnicodeEncodeError:
            # If it has unicode is crashes dateutil's parser, but is unlikely to be the date.
            pass

    # Get the date from our SCOTUS date table
    scotus_dates_found = []
    if not dates and court == 'scotus':
        for citation in citations:
            try:
                # Scotus dates are in the form of a list, since a single citation can refer to several dates.
                found = scotus_dates["%s %s %s" % (citation.volume, citation.reporter, citation.page)]
                if len(found) == 1:
                    scotus_dates_found.extend(found)
            except KeyError:
                pass
        if len(scotus_dates_found) == 1:
            dates = scotus_dates_found

    if not dates:
        # Try to grab the year from the citations, if it's the same in all of them.
        years = set([citation.year for citation in citations if citation.year])
        if len(years) == 1:
            dates.append(datetime.datetime(list(years)[0], 1, 1))

    if not dates:
        try:
            dates = fixes[case_path]['dates']
        except KeyError:
            if 'input_dates' in DEBUG:
                #subprocess.Popen(['firefox', 'file://%s' % case_path], shell=False).communicate()
                print '  No date found for: file://%s' % case_path
                input_date = raw_input('  What should be here (YYYY-MM-DD)? ')
                add_fix(case_path, {'dates': [datetime.datetime.strptime(input_date, '%Y-%m-%d')]})
                dates = [datetime.datetime.strptime(input_date, '%Y-%m-%d')]
            if 'log_bad_dates' in DEBUG:
                # Write the failed case out to file.
                with open('missing_dates.txt', 'a') as out:
                    out.write('%s\n' % case_path)

    if dates:
        if 'date' in DEBUG:
            log_print("  Using date: %s of dates found: %s" % (max(dates), dates))
        return max(dates)
    else:
        if 'date' in DEBUG:
            log_print("  No dates found")
        return []


def get_precedential_status(unpub):
    """
    In Mayer corpus, if 'unpublished' item exists, its an unpublished opinion.
    """
    if unpub is None:
        return 'Published'
    else:
        return 'Unpublished'


def get_docket_number(docket_number, fulltext):
    """
    In Mayer corpus, docket number is pre-parsed in most of the cases.
    We could write this to go back and search the full text for a docket number if docket_number is none
    """
    try:
        path = '//center/text()'
        text_elements = html.xpath(path)
    except AttributeError:
        # Not an HTML element, instead it's a string
        text_elements = [html]
    docket_no_formats = ['Bankruptcy', 'C.A.', 'Case', 'Civ', 'Civil', 'Civil Action', 'Crim', 'Criminal Action',
                         'Docket', 'Misc', 'Record']
    regexes = [
        re.compile('((%s)( Nos?\.)?)|(Nos?(\.| )?)' % "|".join(map(re.escape, docket_no_formats)), re.IGNORECASE),
        re.compile('\d{2}-\d{2,5}'),          # WY-03-071, 01-21574
        re.compile('[A-Z]{2}-[A-Z]{2}'),      # CA-CR 5158
        re.compile('[A-Z]\d{2} \d{4}[A-Z]'),  # C86 1392M
        re.compile('\d{2} [A-Z] \d{4}'),      # 88 C 4330
        re.compile('[A-Z]-\d{2,4}'),          # M-47B (VLB), S-5408
        re.compile('[A-Z]\d{3,}',),
        re.compile('[A-Z]{4,}'),              # SCBD #4983
        re.compile('\d{5,}'),                 # 95816
        re.compile('\d{2},\d{3}'),            # 86,782
        re.compile('([A-Z]\.){4}'),           # S.C.B.D. 3020
        re.compile('\d{2}-[a-z]{2}-\d{4}'),
    ]

    docket_number = None
    outer_break = False
    for t in text_elements:
        if outer_break:
            # Allows breaking the outer loop from the inner loop
            break
        t = clean_string(t).strip('.')
        for regex in regexes:
            if re.search(regex, t):
                docket_number = t
                outer_break = True
                break

    if docket_number:
        if docket_number.startswith('No.'):
            docket_number = docket_number[4:]
        elif docket_number.startswith('Nos.'):
            docket_number = docket_number[5:]
        elif docket_number.startswith('Docket No.'):
            docket_number = docket_number[11:]
        if re.search('^\(.*\)$', docket_number):
            # Starts and ends with parens. Nuke 'em.
            docket_number = docket_number[1:-1]

    if docket_number and re.search('submitted|reversed', docket_number, re.I):
        # False positive. Happens when there's no docket number and the date is incorrectly interpreted.
        docket_number = None
    elif docket_number == 'Not in Source':
        docket_number = None

    if not docket_number:
        try:
            docket_number = fixes[case_path]['docket_number']
        except KeyError:
            if 'northeastern' not in case_path and \
                    'federal_reporter/2d' not in case_path and \
                    court not in ['or', 'orctapp', 'cal'] and \
                    ('unsorted' not in case_path and court not in ['ind']) and \
                    ('pacific_reporter/2d' not in case_path and court not in ['calctapp']):
                # Lots of missing docket numbers here.
                if 'input_docket_number' in DEBUG:
                    subprocess.Popen(['firefox', 'file://%s' % case_path], shell=False).communicate()
                    docket_number = raw_input('  No docket number found. What should be here? ')
                    add_fix(case_path, {'docket_number': docket_number})
                if 'log_bad_docket_numbers' in DEBUG:
                    with open('missing_docket_numbers.txt', 'a') as out:
                        out.write('%s\n' % case_path)

    if 'docket_number' in DEBUG:
        log_print('  Docket Number: %s' % docket_number)
    return docket_number

folderkey = {}

def get_court_object(folder, courtstr):
    """
    For mayer corpus, we probably want to use the folder name for the court.
    """            
    try:
        return folderkey{folder}
    except:
        print('folder name %s not found.' % folder)
            
    return None


def get_judge(judgestr, case_path=None):
    """
    Judges are pre-parsed, we may want to just return the last name though.
    """
    return judgestr

### EA: New code here

skipels = set(['center','italic','bold', 'block_quote', 'underline',
               'page_number', 'opinion', 'citation_line','strikethrough',
               'superscript','heading', 'superscript','subscript','table', 'img',
               'html'])

listels = set(['cross_reference', 'footnote_body', 'footnote_number',
               'footnote_reference', 'opinion_text', 'opinion_byline',
               'dissent_byline','dissent_text',
               'concurrence_byline','concurrence_text'
               ])

seen = listels | set([
        "court","subcourt","panel",'posture', 'citation',
               'syllabus', 'attorneys', 'hearing_date', 'date',
               "report", 'reporter_caption', 'caption','docket','unpublished', 'body']) 

def textFromElements(tree,num):
    """takes in an Element Tree and a list/set of elements and
        returns the text of the elements as a list of dictionaries"""
    texts = defaultdict(list)
    texts["fileNum"] = num            
    for child in tree.iter():        
        if child.tag in skipels:
            continue
        #print child.tag        
        l = ET.tostring(child)
        #ignore tags inside of the tag, such as <center> and <italic>
        text =  re.sub(r'<.*?>', '', l)
        text = text.strip()
        if child.tag not in seen:
            seen.add(child.tag)
            print( '***'+child.tag, num)
            #print( text)
        texts[child.tag].append(text)
    
    texts.default_factory = lambda: None
    return(texts)

def import_mayer(case_path):
    """Open the file, get its contents, convert to XML and extract the meta data.

    Return a document object for saving in the database
    """
    #raw_text = open(case_path).read()    
    #clean_html_tree, complete_html_tree, clean_html_str, body_text = get_html_from_raw_text(raw_text)
    tree = html.parse(case_path)

    sha1 = hashlib.sha1(clean_html_str).hexdigest()
    citations = get_citations_from_tree(complete_html_tree, case_path)
    judges = get_judge(clean_html_tree, case_path)
    court = get_court_object(clean_html_tree, citations, case_path, judges)

    doc = Document(
        source='L',
        sha1=sha1,
        html=clean_html_str,  # we clear this field later, putting the value into html_lawbox.
        date_filed=get_date_filed(clean_html_tree, citations=citations, case_path=case_path, court=court),
        precedential_status=get_precedential_status(),
        judges=judges,
        download_url=case_path,
    )

    cite = Citation()

    docket = Docket(
        docket_number=get_docket_number(
            clean_html_tree,
            case_path=case_path,
            court=court
        ),
        case_name=get_case_name(complete_html_tree, case_path),
        court=court,
    )

    # Necessary for dup_finder.
    path = '//p/text()'
    doc.body_text = ' '.join(clean_html_tree.xpath(path))

    # Add the dict of citations to the object as its attributes.
    citations_as_dict = map_citations_to_models(citations)
    for k, v in citations_as_dict.iteritems():
        setattr(cite, k, v)

    doc.citation = cite
    doc.docket = docket

    return doc





def main():
    parser = argparse.ArgumentParser(description='Import the corpus on state courts provided by jonathan mayer')
    parser.add_argument('-s', '--simulate', default=False, required=False, action='store_true',
                        help='Run the code in simulate mode, making no permanent changes.')
    parser.add_argument('-d', '--dir', type=readable_dir,
                        help='The directory where the lawbox bulk data can be found.')
    parser.add_argument('-f', '--file', type=str, default="index.txt", required=False, dest="file_name",
                        help="The file that has all the URLs to import, one per line.")
    parser.add_argument('-l', '--line', type=int, default=1, required=False,
                        help='If provided, this will be the line number in the index file where we resume processing.')
    parser.add_argument('-r', '--resume', default=False, required=False, action='store_true',
                        help='Use the saved marker to resume operation where it last failed.')
    parser.add_argument('-x', '--random', default=False, required=False, action='store_true',
                        help='Pick cases randomly rather than serially.')
    parser.add_argument('-m', '--marker', type=str, default='lawbox_progress_marker.txt', required=False,
                        help="The name of the file that tracks the progress (useful if multiple versions run at same time)")
    parser.add_argument('-e', '--end', type=int, required=False, default=2000000,
                        help="An optional endpoint for an importer.")
    args = parser.parse_args()

    if args.dir:
        def case_generator(dir_root):
            """Yield cases, one by one to the importer by recursing and iterating the import directory"""
            for root, dirnames, filenames in os.walk(dir_root):
                for filename in fnmatch.filter(filenames, '*xml'): # ETA
                    yield os.path.join(root, filename)

        cases = case_generator(args.root)
        i = 0
    else:
        def generate_random_line(file_name):
            while True:
                total_bytes = os.stat(file_name).st_size
                random_point = random.randint(0, total_bytes)
                f = open(file_name)
                f.seek(random_point)
                f.readline()  # skip this line to clear the partial line
                yield f.readline().strip()

        def case_generator(line_number):
            """Yield cases from the index file."""
            enumerated_line_number = line_number - 1  # The enumeration is zero-index, but files are one-index.
            index_file = open(args.file_name)
            for i, line in enumerate(index_file):
                if i >= enumerated_line_number:
                    yield line.strip()

        if args.random:
            cases = generate_random_line(args.file_name)
            i = 0
        elif args.resume:
            with open(args.marker) as marker:
                resume_point = int(marker.read().strip())
            cases = case_generator(resume_point)
            i = resume_point
        else:
            cases = case_generator(args.line)
            i = args.line

    for case_path in cases:
        if i % 1000 == 0:
            db.reset_queries()  # Else we leak memory when DEBUG is True

        if 'counter' in DEBUG:  #and i % 1000 == 0:
            log_print("\n%s: Doing case (%s): file://%s" % (datetime.datetime.now(), i, case_path))
        try:
            doc = import_mayer(case_path)
            
            duplicates = 0 # find_duplicates(doc, case_path)
            if not args.simulate:
                if len(duplicates) == 0:
                    doc.html_lawbox, blocked = anonymize(doc.html)
                    doc.html = ''
                    if blocked:
                        doc.blocked = True
                        doc.date_blocked = now()
                        # Save nothing to the index for now (it'll get done when we find citations)
                    save_doc_and_cite(doc, index=False)
                if len(duplicates) == 1:
                    dup_helpers.merge_cases_simple(doc, duplicates[0])
                if len(duplicates) > 1:
                    #complex_merge
                    if 'log_multimerge' in DEBUG:
                        with open('index_multimerge.txt', 'a') as log:
                            log.write('%s\n' % case_path)
            if args.resume:
                # Don't change the progress marker unless you're in resume mode.
                with open(args.marker, 'w') as marker:
                    marker.write(str(i + 1))  # Files are one-index, not zero-index
            with open('lawbox_fix_file.pkl', 'wb') as fix_file:
                pickle.dump(fixes, fix_file)
            i += 1
            if i == args.end:
                log_print("Hit the endpoint after importing number %s. Breaking." % i)
                break
        except Exception, err:
            log_print(traceback.format_exc())
            exit(1)

if __name__ == '__main__':
    main()
