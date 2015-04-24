# -*- coding: utf-8 -*-
"""
Created on Fri Apr 24 13:11:27 2015

Things I think are unneeded from lawbox import

@author: elliott
"""

def get_citations_from_tree(complete_html_tree, case_path):
    path = '//center[descendant::text()[not(starts-with(normalize-space(.), "No.") or starts-with(normalize-space(.), "Case No.") or starts-with(normalize-space(.), "Record No."))]]'
    citations = []
    for e in complete_html_tree.xpath(path):
        text = tostring(e, method='text', encoding='unicode')
        citations.extend(get_citations(text, html=False, do_defendant=False))
    if not citations:
        path = '//title/text()'
        text = complete_html_tree.xpath(path)[0]
        citations = get_citations(text, html=False, do_post_citation=False, do_defendant=False)

    if not citations:
        try:
            citations = fixes[case_path]['citations']
        except KeyError:
            if 'input_citations' in DEBUG:
                subprocess.Popen(['firefox', 'file://%s' % case_path], shell=False).communicate()
                input_citation = raw_input('  No citations found. What should be here? ')
                citation_objects = get_citations(input_citation, html=False, do_post_citation=False, do_defendant=False)
                add_fix(case_path, {'citations': citation_objects})
                citations = citation_objects

    if 'citations' in DEBUG and len(citations):
        cite_strs = [str(cite.__dict__) for cite in citations]
        log_print("  Citations found: %s" % ',\n                   '.join(cite_strs))
    elif 'citations' in DEBUG:
        log_print("  No citations found!")
    return citations


def get_case_name(complete_html_tree, case_path):
    path = '//head/title/text()'
    # Text looks like: 'In re 221A Holding Corp., Inc, 1 BR 506 - Dist. Court, ED Pennsylvania 1979'
    s = complete_html_tree.xpath(path)[0].rsplit('-', 1)[0].rsplit(',', 1)[0]
    # returns 'In re 221A Holding Corp., Inc.'
    case_name = harmonize(clean_string(titlecase(s)))
    if not s:
        try:
            case_name = fixes[case_path]['case_name']
        except KeyError:
            if 'input_case_names' in DEBUG:
                if 'firefox' in DEBUG:
                    subprocess.Popen(['firefox', 'file://%s' % case_path], shell=False).communicate()
                input_case_name = raw_input('  No case name found. What should be here? ')
                input_case_name = unicode(input_case_name)
                add_fix(case_path, {'case_name': input_case_name})
                case_name = input_case_name

    if 'case_name' in DEBUG:
        log_print("  Case name: %s" % case_name)
    return case_name
    
    
def readable_dir(prospective_dir):
    if not os.path.isdir(prospective_dir):
        raise argparse.ArgumentTypeError("readable_dir:{0} is not a valid path".format(prospective_dir))
    if os.access(prospective_dir, os.R_OK):
        return prospective_dir
    else:
        raise argparse.ArgumentTypeError("readable_dir:{0} is not a readable dir".format(prospective_dir))


def needs_dup_check(doc):
    """Checks the document to see whether we need to run our duplicate checking code.

    Based on minimum dates found in the CL database on 2013-10-10 using:
    courtlistener=> select "court_id", min(date_filed) from "Document" group by court_id order by min(date_filed);
    """
    start_dates = {'scotus': '1754-09-01', 'ca5': '1901-07-15', 'ca2': '1904-06-22', 'ca1': '1940-01-23',
                   'cafc': '1944-09-13', 'ca3': '1947-03-24', 'ca4': '1949-01-15', 'cadc': '1949-05-16',
                   'ca9': '1949-06-30', 'ca10': '1949-10-31', 'ca8': '1949-11-16', 'ca7': '1949-11-17',
                   'ca6': '1949-11-17', 'ccpa': '1949-12-12', 'eca': '1949-12-16', 'uscfc': '1960-01-20',
                   'mont': '1972-01-03', 'ca11': '1981-10-20', 'miss': '1982-02-04', 'tenncrimapp': '1988-12-08',
                   'tennctapp': '1993-01-28', 'vactapp': '1995-05-02', 'va': '1995-06-09', 'tenn': '1995-10-09',
                   'sd': '1996-01-10', 'nd': '1996-09-03', 'ind': '1997-12-31', 'or': '1998-01-08',
                   'ndctapp': '1998-07-07', 'cit': '1999-01-05', 'cavc': '2000-01-12', 'mich': '2000-12-18',
                   'tex': '2001-10-02', 'ariz': '2002-01-09', 'fiscr': '2002-11-18', 'armfor': '2003-11-18',
                   'idahoctapp': '2006-06-15', 'vt': '2006-08-04', 'idaho': '2006-11-28', 'nmctapp': '2007-08-31',
                   'nm': '2008-12-01', 'hawapp': '2010-01-04', 'haw': '2010-01-07', 'cal': '2011-04-22',
                   'washctapp': '2011-11-08', 'ri': '2012-10-05', 'bap9': '2012-10-10', 'wyo': '2012-12-28',
                   'alaska': '2013-01-09', 'wva': '2013-01-14', 'utah': '2013-01-15', 'tax': '2013-01-30',
                   'ill': '2013-02-04', 'wis': '2013-02-13', 'calctapp': '2013-02-25', 'wash': '2013-02-28',
                   'nev': '2013-03-13', 'nebctapp': '2013-04-02', 'neb': '2013-04-05', 'njsuperctappdiv': '2013-07-30',
                   'nj': '2013-07-30', 'ark': '2013-08-02', 'arkctapp': '2013-08-28', 'illappct': '2013-09-19', }
    try:
        if doc.date_filed >= datetime.datetime.strptime(start_dates[doc.court_id], '%Y-%m-%d'):
            return True
    except KeyError:
        pass
    return False


def find_duplicates(doc, case_path):
    """Return True if it should be saved, else False"""
    log_print("Running duplicate checks...")

    # 1. Is the item completely outside of the current corpus?
    if not needs_dup_check(doc):
        log_print("  - Not a duplicate: Outside of date range for selected court.")
        return []
    else:
        log_print("  - Could be a duplicate: Inside of date range for selected court.")

    # 2. Can we find any duplicates and information about them?
    stats, candidates = dup_finder.get_dup_stats(doc)
    if len(candidates) == 0:
        log_print("  - Not a duplicate: No candidate matches found.")
        return []
    elif len(candidates) == 1:

        if doc.docket.docket_number and candidates[0].get('docketNumber') is not None:
            # One in the other or vice versa
            if (re.sub("(\D|0)", "", candidates[0]['docketNumber']) in
                                        re.sub("(\D|0)", "", doc.docket.docket_number)) or \
               (re.sub("(\D|0)", "", doc.docket.docket_number) in
                                        re.sub("(\D|0)", "", candidates[0]['docketNumber'])):
                log_print("  - Duplicate found: Only one candidate returned and docket number matches.")
                return [candidates[0]['id']]
            else:
                if doc.docket.court_id == 'cit':
                    # CIT documents have neutral citations in the database. Look that up and compare against that.
                    candidate_doc = Document.objects.get(pk=candidates[0]['id'])
                    if doc.citation.neutral_cite and candidate_doc.citation.neutral_cite:
                        if candidate_doc.citation.neutral_cite in doc.docket.docket_number:
                            log_print('  - Duplicate found: One candidate from CIT and its neutral citation matches the new document\'s docket number.')
                            return [candidates[0]['id']]
                else:
                    log_print("  - Not a duplicate: Only one candidate but docket number differs.")
                return []
        else:
            log_print("  - Skipping docket_number dup check.")

        if doc.citation.case_name == candidates[0].get('caseName'):
            log_print("  - Duplicate found: Only one candidate and case name is a perfect match.")
            return [candidates[0]['id']]

        if dup_helpers.case_name_in_candidate(doc.citation.case_name, candidates[0].get('caseName')):
            log_print("  - Duplicate found: All words in new document's case name are in the candidate's case name (%s)" % candidates[0].get('caseName'))
            return [candidates[0]['id']]

    else:
        # More than one candidate.
        if doc.docket.docket_number:
            dups_by_docket_number = dup_helpers.find_same_docket_numbers(doc, candidates)
            if len(dups_by_docket_number) > 1:
                log_print("  - Duplicates found: %s candidates matched by docket number." % len(dups_by_docket_number))
                return [can['id'] for can in dups_by_docket_number]
            elif len(dups_by_docket_number) == 1:
                log_print("  - Duplicate found: Multiple candidates returned, but one matched by docket number.")
                return [dups_by_docket_number[0]['id']]
            else:
                log_print("  - Could be a duplicate: Unable to find good match via docket number.")
        else:
            log_print("  - Skipping docket_number dup check.")

    # 3. Filter out obviously bad cases and then pass remainder forward for manual review.

    filtered_candidates, filtered_stats = dup_helpers.filter_by_stats(candidates, stats)
    log_print("  - %s candidates before filtering. With stats: %s" % (stats['candidate_count'], stats['cos_sims']))
    log_print("  - %s candidates after filtering. Using filtered stats: %s" % (filtered_stats['candidate_count'],
                                                                               filtered_stats['cos_sims']))
    if len(filtered_candidates) == 0:
        log_print("  - Not a duplicate: After filtering no good candidates remained.")
        return []
    elif len(filtered_candidates) == 1 and filtered_stats['cos_sims'][0] > 0.93:
        log_print("  - Duplicate found: One candidate after filtering and cosine similarity is high (%s)" % filtered_stats['cos_sims'][0])
        return [filtered_candidates[0]['id']]
    else:
        duplicates = []
        high_sims_count = len([sim for sim in filtered_stats['cos_sims'] if sim > 0.98])
        low_sims_count = len([sim for sim in filtered_stats['cos_sims'] if sim < 0.95])
        for k in range(0, len(filtered_candidates)):
            if all([(high_sims_count == 1),  # Only one high score
                    (low_sims_count == filtered_stats['candidate_count'] - 1)  # All but one have low scores
            ]):
                # If only one of the items is very high, then we can ignore the others and assume it's right
                if filtered_stats['cos_sims'][k] > 0.98:
                    duplicates.append(filtered_candidates[k]['id'])
                    break
                else:
                    # ignore the others
                    continue
            else:
                # Have to determine by "hand"
                log_print("  %s) Case name: %s" % (k + 1, doc.citation.case_name))
                log_print("                 %s" % filtered_candidates[k]['caseName'])
                log_print("      Docket nums: %s" % doc.docket.docket_number)
                log_print("                   %s" % filtered_candidates[k].get('docketNumber', 'None'))
                log_print("      Cosine Similarity: %s" % filtered_stats['cos_sims'][k])
                log_print("      Candidate URL: file://%s" % case_path)
                log_print("      Match URL: https://www.courtlistener.com%s" %
                                             (filtered_candidates[k]['absolute_url']))

                choice = raw_input("Is this a duplicate? [Y/n]: ")
                choice = choice or "y"
                if choice == 'y':
                    duplicates.append(filtered_candidates[k]['id'])

        if len(duplicates) == 0:
            log_print("  - Not a duplicate: Manual determination found no matches.")
            return []
        elif len(duplicates) == 1:
            log_print("  - Duplicate found: Manual determination found one match.")
            return [duplicates[0]]
        elif len(duplicates) > 1:
            log_print("  - Duplicates found: Manual determination found %s matches." % len(duplicates))
            return duplicates    