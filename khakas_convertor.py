from lxml import etree
import os
import re
import copy


class ConLabEAFConvertor:
    """
    Contains methods for converting eafs in the old ConLab
    to the new ConLab format and adding grammatical tags
    in the process.
    """
    rxSplitParts = re.compile('(?:^|[-=.])[^-=а-яёА-ЯЁӱӰ ]+|<[^<>]+>')
    rxWord = re.compile('\\b\\w[\\w-]*\\w\\b|\\b\\w\\b')

    def __init__(self):
        self.srcDir = 'eaf_to_process'
        self.targetDir = 'eaf'
        self.tlis = {}      # time labels
        self.rxTierType = re.compile('^(.+)_(Transcription|Lemma|'
                                     'POS|Morph|Gloss|Words)(?:-txt|-gls)?.*')
        self.lastUsedAID = 0
        self.refTiers = {}
        self.morphTiers = {}
        self.lemmaTiers = {}
        self.posTiers = {}
        self.glossTiers = {}
        self.wordTiers = {}
        self.aid2pos = {}
        self.grammRules = []
        self.load_gramm_rules('gramRules.txt')

    @staticmethod
    def prepare_rule(rule):
        """
        Make a compiled regex out of a rule represented as a string.
        """
        def replReg(s):
            if "'" in s:
                return ''
            return ' re.search(\'' + s +\
                   '\', parts) is not None or ' +\
                   're.search(\'' + s +\
                   '\', gloss) is not None '
        ruleParts = rule.split('"')
        rule = ''
        for i in range(len(ruleParts)):
            if i % 2 == 0:
                rule += re.sub('([^\\[\\]~|& \t\']+)', ' \'\\1\' in tagsAndGlosses ',
                               ruleParts[i]).replace('|', ' or ').replace('&', ' and ')\
                                            .replace('~', ' not ').replace('[', '(').replace(']', ')')
            else:
                rule += replReg(ruleParts[i])
        return rule

    def load_gramm_rules(self, fname):
        """
        Load main set of rules for converting the glosses into bags
        of grammatical tags.
        """
        if len(fname) <= 0 or not os.path.isfile(fname):
            return
        rules = []
        f = open(fname, 'r', encoding='utf-8-sig')
        for line in f:
            line = line.strip()
            if len(line) > 0:
                rule = [i.strip() for i in line.split('->')]
                if len(rule) != 2:
                    continue
                rule[1] = set(rule[1].split(','))
                rule[0] = self.prepare_rule(rule[0])
                rules.append(rule)
        f.close()
        self.grammRules = rules

    def restore_gramm(self, pos, gloss, parts=''):
        """
        Restore grammatical tags from the glosses using the rules
        provided in gramRules.txt.
        """


        grammTags = set()
        tagsAndGlosses = set()
        if gloss:
            tagsAndGlosses |= set(gl.strip('-=:.<>')
                                for gl in self.rxSplitParts.findall(gloss))
        #if len(self.grammRules) > 0:
         #   for rule in self.grammRules:
          #      if eval(rule[0]):
           #         grammTags |= rule[1]
        # if gloss:
        #     print(gloss)
        #     print(tagsAndGlosses)

        toSplit = ['dimin.dimin', 'refl.rec', 'refl.caus', 'nf.neg', 'pl.3pos', 
                    'caus.caus', 'pass.rec', 'neg.conv.abl', 'caus.pass', 'dur.iter', 
                    'gen1.3pos', 'gen1.dial.3pos', '3pos.All', '3pos.Dat', 'imp.3',
                    'imp.2pl', 'imp.1sg', 'imp.1pl', 'all.abl', 'all1.abl', '3pos.attr',
                    '3pos.dat']
        toSplitFirst = ['imp.1.incl', 'imp.1pl.incl', 'imp.1pl.incl.dial']
        notDial = ['prosp.dial', 'prespt.dial', 'prespt1.dial']

        for gl in tagsAndGlosses:
            gl = gl.lower().strip('?')
            if gl and gl in toSplit:
                grammTags.add(gl.split('.')[-1].replace('.dial', ''))
                grammTags.add('.'.join(gl.split('.')[:-1]).replace('.dial', ''))
            elif gl and gl in toSplitFirst:
                grammTags.add('imp')
                grammTags.add(gl.strip('imp.').replace('.dial', ''))
            else:
                if gl not in notDial:
                    grammTags.add(gl.replace('.dial', ''))
                else:
                    grammTags.add(gl)
        if pos and len(pos) > 0:
            grammTags.add(pos.lower())

        if len(tagsAndGlosses) == 0 and pos == 'v':
            grammTags.add('imp')
            grammTags.add('2sg')
            # print(gloss)
            # print(grammTags)

        if '(' in grammTags:
            print(grammTags)
            print(gloss)

        return ','.join(sorted(grammTags))

    def get_tlis(self, srcTree):
        """
        Retrieve and return all time labels from the XML tree.
        """
        tlis = {}
        iTli = 0
        for tli in srcTree.xpath('/ANNOTATION_DOCUMENT/TIME_ORDER/TIME_SLOT'):
            timeValue = ''
            if 'TIME_VALUE' in tli.attrib:
                timeValue = tli.attrib['TIME_VALUE']
            tlis[tli.attrib['TIME_SLOT_ID']] = {'n': iTli, 'time': timeValue}
            iTli += 1
        return tlis

    def get_tier_segment_ids(self, tierNode):
        """
        For an association-aligned tier, return a dictionary
        {ID of the parent annotation -> ID of the current annotation}
        """
        segIDs = {}
        for node in tierNode.xpath('ANNOTATION/REF_ANNOTATION'):
            segIDs[node.attrib['ANNOTATION_REF']] = node.attrib['ANNOTATION_ID']
        return segIDs

    def get_segment_values(self, tierNode):
        """
        Return a dictionary {annotation ID -> annotation text}
        """
        segIDs = {}
        for node in tierNode.xpath('ANNOTATION/REF_ANNOTATION'):
            segIDs[node.attrib['ANNOTATION_ID']] = node.xpath('ANNOTATION_VALUE')[0].text
        return segIDs

    def get_annotation_ids(self, srcTree):
        """
        Traverse the tree and save data from the Lemma, POS,
        Morph and Gloss tiers for later use.
        """
        for tierNode in srcTree.xpath('/ANNOTATION_DOCUMENT/TIER'):
            if 'TIER_ID' not in tierNode.attrib:
                continue
            tierID = tierNode.attrib['TIER_ID']
            mTierType = self.rxTierType.search(tierID)
            if mTierType is None:
                continue
            participant = mTierType.group(1)
            tierType = mTierType.group(2)
            if tierType not in ('Lemma', 'POS', 'Gloss', 'Morph', 'Words', 'Word'):
                continue
            segIDs = self.get_tier_segment_ids(tierNode)
            # print(segIDs)
            if tierType == 'Lemma':
                self.lemmaTiers[participant] = segIDs
            elif tierType == 'POS':
                self.posTiers[participant] = segIDs
                self.aid2pos.update(self.get_segment_values(tierNode))
            if tierType == 'Morph':
                self.morphTiers[participant] = {}
                for node in tierNode.xpath('ANNOTATION/REF_ANNOTATION'):
                    self.morphTiers[participant][node.attrib['ANNOTATION_ID']] = node.attrib['ANNOTATION_REF']
            elif tierType == 'Gloss':
                self.glossTiers[participant] = segIDs
            elif tierType == 'Words':
                self.wordTiers[participant] = segIDs

    def read_ref_tier(self, tierNode):
        """
        Read the time-aligned baseline (reference) tier and
        save its data for later use.
        """
        aID2sent = {}
        segments = tierNode.xpath('ANNOTATION/ALIGNABLE_ANNOTATION')
        for segment in segments:
            if 'ANNOTATION_ID' in segment.attrib:
                aID = segment.attrib['ANNOTATION_ID']
                try:
                    aID2sent[aID] = segment.xpath('ANNOTATION_VALUE')[0].text.strip()
                except AttributeError:
                    aID2sent[aID] = ''
            else:
                continue
        return aID2sent

    def get_word_tier(self, morphTierNode, participant):
        """
        Make and return a Word tier out of Morph tier
        """
        wordTierNode = copy.deepcopy(morphTierNode)
        wordTierNode.attrib['TIER_ID'] = wordTierNode.attrib['TIER_ID'].replace('_Morph', '_Word')
        sent2words = {}
        for sentID in self.refTiers[participant]:
            sent2words[sentID] = self.rxWord.findall(self.refTiers[participant][sentID].lower())
        print(sent2words)
        iWord = 0
        prevSentID = ''
        for segment in wordTierNode.xpath('ANNOTATION/REF_ANNOTATION'):
            curSentID = segment.attrib['ANNOTATION_REF']
            if curSentID != prevSentID:
                iWord = 0
            prevSentID = curSentID
            wordFromMorph = re.sub('[-0]', '', segment.xpath('ANNOTATION_VALUE')[0].text)
            if iWord < len(sent2words[curSentID]):
                if (sent2words[curSentID][iWord] != wordFromMorph
                        and iWord < len(sent2words[curSentID]) - 1
                        and sent2words[curSentID][iWord + 1] == wordFromMorph):
                    iWord += 1      # simple fix for single incomplete tokens
                segment.xpath('ANNOTATION_VALUE')[0].text = sent2words[curSentID][iWord]
            else:
                segment.xpath('ANNOTATION_VALUE')[0].text = wordFromMorph
            iWord += 1
        return wordTierNode

    def get_gramm_tier(self, morphTierNode):
        """
        Make and return a Gramm tier out of a Morph tier (using
        previously saved POS data)
        """
        grammTierNode = copy.deepcopy(morphTierNode)
        grammTierNode.attrib['TIER_ID'] = grammTierNode.attrib['TIER_ID'].replace('_Gloss', '_Gramm')
        for segment in grammTierNode.xpath('ANNOTATION/REF_ANNOTATION'):
            curPosID = segment.attrib['ANNOTATION_REF']
            gloss = segment.xpath('ANNOTATION_VALUE')[0].text
            pos = self.aid2pos[curPosID]           
            segment.xpath('ANNOTATION_VALUE')[0].text = self.restore_gramm(pos, gloss)
        return grammTierNode

    def reindex_segments(self, tierNode):
        """
        Assign all tier annotations new IDs.
        """
        for segment in tierNode.xpath('ANNOTATION/REF_ANNOTATION'):
            if 'PREVIOUS_ANNOTATION' in segment.attrib:
                segment.attrib['PREVIOUS_ANNOTATION'] = 'a' + str(self.lastUsedAID)
            self.lastUsedAID += 1
            segment.attrib['ANNOTATION_ID'] = 'a' + str(self.lastUsedAID)

    def reattach_morph_segments(self, tierNode, segmentIDs, participant):
        """
        Attach the Morph tier annotations to POS, instead of Transcription.
        """
        for segment in tierNode.xpath('ANNOTATION/REF_ANNOTATION'):
            if 'PREVIOUS_ANNOTATION' in segment.attrib:
                del segment.attrib['PREVIOUS_ANNOTATION']
            try:
                if segment.attrib['ANNOTATION_ID'] not in self.lemmaTiers[participant]:
                    segment.getparent().getparent().remove(segment.getparent())
                    continue
                segment.attrib['ANNOTATION_REF'] = segmentIDs[participant][segment.attrib['ANNOTATION_ID']]
            except KeyError:
                segment.getparent().getparent().remove(segment.getparent())

    def reattach_non_morph_segments(self, tierNode, segmentIDs, participant):
        """
        Attach any association-aligned tier to another tier.
        """
        for segment in tierNode.xpath('ANNOTATION/REF_ANNOTATION'):
            if 'PREVIOUS_ANNOTATION' in segment.attrib:
                del segment.attrib['PREVIOUS_ANNOTATION']
            try:
                segment.attrib['ANNOTATION_REF'] = segmentIDs[participant][segment.attrib['ANNOTATION_REF']]
            except KeyError:
                segment.getparent().getparent().remove(segment.getparent())


    def convert_file(self, fnameSrc, fnameTarget):
        """
        Convert one EAF file and save the output as fnameTarget
        """
        srcTree = etree.parse(fnameSrc)
        self.tlis = self.get_tlis(srcTree)
        self.refTiers = {}      # participant -> {ID -> text}
        self.lastUsedAID = 0
        self.morphTiers = {}
        self.lemmaTiers = {}
        self.posTiers = {}
        self.glossTiers = {}
        self.wordTiers = {}
        self.aid2pos = {}
        self.get_annotation_ids(srcTree)
        self.lastUsedAID = int(srcTree.xpath('/ANNOTATION_DOCUMENT/HEADER/'
                                             'PROPERTY[@NAME=\'lastUsedAnnotationId\']')[0].text)
        for tierNode in srcTree.xpath('/ANNOTATION_DOCUMENT/TIER'):
            
            if 'TIER_ID' not in tierNode.attrib:
                continue
            tierID = tierNode.attrib['TIER_ID']
            mTierType = self.rxTierType.search(tierID)
            if mTierType is None:
                continue
            participant = mTierType.group(1)
            tierType = mTierType.group(2)
            #print(mTierType.group(2))
            if tierType == 'Transcription':
                self.refTiers[participant] = self.read_ref_tier(tierNode)
            elif tierType == 'Morph':
                parentNode = tierNode.getparent()
                tierIndex = parentNode.index(tierNode)
                #parentNode.insert(tierIndex, self.get_word_tier(tierNode, participant))
                self.reattach_morph_segments(tierNode, self.posTiers, participant)
                self.reindex_segments(tierNode)
                tierNode.attrib['PARENT_REF'] = re.sub('_Transcription-txt-.*', '_POS-txt-en',
                                                       tierNode.attrib['PARENT_REF'])
                tierNode.attrib['PARENT_REF'] = re.sub('_Words-txt-.*', '_POS-txt-en',
                                                       tierNode.attrib['PARENT_REF'])
                tierNode.attrib['LINGUISTIC_TYPE_REF'] = 'association'
            elif tierType == 'POS':
                self.reattach_non_morph_segments(tierNode, self.lemmaTiers, participant)
                tierNode.attrib['PARENT_REF'] = tierNode.attrib['PARENT_REF'].replace('_Morph', '_Lemma')
            elif tierType == 'Gloss':
                self.reattach_non_morph_segments(tierNode, self.posTiers, participant)
                tierNode.attrib['PARENT_REF'] = re.sub('_Morph-txt-.*', '_POS-txt-en',
                                                       tierNode.attrib['PARENT_REF'])
                parentNode = tierNode.getparent()
                tierIndex = parentNode.index(tierNode)
                parentNode.insert(tierIndex + 2, self.get_gramm_tier(tierNode))
                self.reindex_segments(tierNode)
                
            elif tierType == 'Lemma':
                self.reattach_non_morph_segments(tierNode, self.morphTiers, participant)
                tierNode.attrib['PARENT_REF'] = tierNode.attrib['PARENT_REF'].replace('_Morph', '_Word')


            elif tierType == 'Words':
                tierNode.attrib['TIER_ID'] = tierNode.attrib['TIER_ID'].replace('Words', 'Word')
        srcTree.xpath('/ANNOTATION_DOCUMENT/HEADER/'
                      'PROPERTY[@NAME=\'lastUsedAnnotationId\']')[0].text = str(self.lastUsedAID)
        srcTree.write(fnameTarget, encoding='utf-8', pretty_print=True)

    def convert_corpus(self):
        """
        Take every EAF file from the source directory subtree,
        convert it to ConLab format and store it in the target directory.
        """
        nFiles = 0
        for path, dirs, files in os.walk(self.srcDir):
            for fname in files:
                if not fname.lower().endswith('.eaf'):
                    continue
                print(fname)
                nFiles += 1
                srcPath = os.path.join(path, fname)
                targetPath = os.path.join(self.targetDir + path[len(self.srcDir):],
                                          fname)
                if srcPath == targetPath:
                    print('Error: scrPath == targetPath')
                    continue
                self.convert_file(srcPath, targetPath)
        print('Done,', nFiles, 'files converted.')


if __name__ == '__main__':
    convertor = ConLabEAFConvertor()
    convertor.convert_corpus()
