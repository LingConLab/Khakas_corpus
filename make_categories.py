import json

with open('glossy_khak.csv', 'r', encoding='utf-8') as f:
	lines = f.readlines()
	for indx, line in enumerate(lines):
		lines[indx] = line.split(';')

categories = dict()
categories['khakas'] = {}
categories['russian'] = {}

for line in lines:
	categories['khakas'][line[0].strip().lower()] = line[1].strip().lower()


with open('./convertors/conf/categories.json', 'w', encoding='utf-8') as fw2:
	json.dump(categories, fp=fw2, ensure_ascii=False, indent=1)