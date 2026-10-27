"""Build annual commuting indicators from SCB bulk CSV and official lookup workbooks.

Strict validation: never treat missing, suppressed or unmapped municipality pairs
as zeros. Fails rather than publishing misleading FA-border shares.
"""
from __future__ import annotations
import io, json, re, zipfile
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

BASE=Path(__file__).resolve().parent.parent
OUT=BASE/'docs/data/summary.json'
LABELS_OUT=BASE/'docs/data/geo_labels.json'
ROOT='https://www.scb.se/contentassets/c4b8142033a9440ca53725ca32321a74/'
URLS={
 'commute':'https://www.statistikdatabasen.scb.se/Resources/PX/bulk/ssd/sv/TAB1830_sv.zip',
 'fa':ROOT+'fa-regioner-2025-ar-indelning.xlsx',
 'skr':ROOT+'kommungruppsindelning-2023.xlsx'
}
def download(url):
    r=requests.get(url,timeout=180,headers={'User-Agent':'Lulea-statistik/pendling_trend (public-statistics-research)'})
    r.raise_for_status()
    return r.content

def extract_code(x):
    s=str(x).strip()
    m=re.match(r'^(\d{4})(?:\D|$)',s)
    return m.group(1) if m else None

def load_lookup(source, kind):
    raw=download(source)
    book=pd.ExcelFile(io.BytesIO(raw))
    if kind=='fa':
        df=pd.read_excel(book,sheet_name='FA25',dtype=str)
        needed={'KommunKod','FA25Nr','FA25Namn'}
        if not needed.issubset(df.columns):
            raise RuntimeError('FA25 missing expected fields: '+str(sorted(needed-set(df.columns))))
        df=df.dropna(subset=['KommunKod','FA25Nr'])
        mapping={}
        for _,row in df.iterrows():
            code=str(row['KommunKod']).strip().zfill(4)
            if not re.fullmatch(r'\d{4}',code):
                raise RuntimeError('Unexpected FA25 municipality code: '+code)
            group=str(row['FA25Nr']).strip()
            if code in mapping and mapping[code]!=group:
                raise RuntimeError('Conflicting FA region for '+code)
            mapping[code]=group
        if len(mapping)!=290:
            raise RuntimeError(f'FA25 has {len(mapping)} municipality mappings, expected 290')
        print('FA25 verified municipalities:',len(mapping),'regions:',len(set(mapping.values())))
        return mapping
    print(kind,'sheets:',book.sheet_names)
    candidates=[]
    for name in book.sheet_names:
        df=pd.read_excel(book,sheet_name=name,header=None,dtype=str).fillna('')
        print(kind,name,'shape',df.shape,'first rows',df.head(4).to_string(index=False,header=False)[:800])
        for j in range(df.shape[1]):
            codes=df.iloc[:,j].map(extract_code)
            unique=set(codes.dropna())
            if len(unique)<150:continue
            for k in range(df.shape[1]):
                if k==j:continue
                values=df.iloc[:,k].astype(str).str.strip()
                paired=[(c,v) for c,v in zip(codes,values) if c and v and v.lower()!='nan']
                if len(paired)<150:continue
                vals={c:v for c,v in paired}
                distinct=len(set(vals.values()))
                # FA regions ~60, SKR groups 9; avoid municipality-name columns.
                lower,upper=(20,100) if kind=='fa' else (7,12)
                if lower<=distinct<=upper and len(vals)>=280:
                    candidates.append((len(vals),abs(distinct-(60 if kind=='fa' else 9)),str(name),j,k,vals))
    if not candidates:
        raise RuntimeError(kind+' mapping could not be identified reliably; review workbook columns in log')
    candidates.sort(key=lambda x:(-x[0],x[1]))
    best=candidates[0]
    print(kind,'selected sheet',best[2],'code column',best[3],'group column',best[4],'distinct',len(set(best[5].values())))
    if kind=='skr':
        # The source includes a header/extra code mapped to the literal
        # heading 'Gruppkod'. Never allow it as a tenth SKR group.
        unexpected={c:v for c,v in best[5].items() if v not in SKR_GROUP_NAMES}
        if unexpected:
            print('Ignored non-SKR classification rows:',unexpected,flush=True)
        valid={c:v for c,v in best[5].items() if v in SKR_GROUP_NAMES}
        if len(valid)!=290 or set(valid.values())!=set(SKR_GROUP_NAMES):
            raise RuntimeError('Invalid SKR 2023 mapping: '+str((len(valid), sorted(set(valid.values())))))
        return valid
    return best[5]


# Official 2023 SKR municipality group names. The codes remain data join keys.
SKR_GROUP_NAMES={
    'A1':'Storstäder',
    'A2':'Pendlingskommun nära storstad',
    'B3':'Större stad',
    'B4':'Pendlingskommun nära större stad',
    'B5':'Lågpendlingskommun nära större stad',
    'C6':'Mindre stad/tätort',
    'C7':'Pendlingskommun nära mindre stad/tätort',
    'C8':'Landsbygdskommun',
    'C9':'Landsbygdskommun med besöksnäring',
}

def load_geo_names(fa,skr):
    """Resolve all visible names using SCB's official FA25 municipality workbook.

    Never guess names from codes. Fail the build if the source layout changes.
    """
    df=pd.read_excel(io.BytesIO(download(URLS['fa'])),sheet_name='FA25',dtype=str).fillna('')
    required={'KommunKod','FA25Nr','FA25Namn'}
    if not required.issubset(df.columns):
        raise RuntimeError('FA25 labels missing fields: '+str(sorted(required-set(df.columns))))
    df=df.loc[df['KommunKod'].astype(str).str.strip().ne('')].copy()
    if len(df)!=290:
        raise RuntimeError(f'FA25 label source expected 290 municipalities, got {len(df)}')

    def municipality_name(value):
        name=str(value).strip()
        name=re.sub(r'^\d{4}\s+', '', name)
        return name

    # Names may be headed KommunNamn or Kommun in different workbook releases.
    # Only a text column identifying every municipality uniquely is accepted.
    candidates=[]
    for col in df.columns:
        if col in required:continue
        vals=df[col].map(municipality_name)
        if (vals.str.len().ge(2).all() and vals.str.contains('[A-Za-zÅÄÖåäö]',regex=True).all()
            and vals.nunique()==290):
            preference=0 if re.search(r'kommun.*namn|namn.*kommun',str(col),re.I) else (1 if re.search('kommun',str(col),re.I) else 2)
            candidates.append((preference,str(col),vals))
    if not candidates:
        raise RuntimeError('No verified municipality-name column in FA25 workbook: '+str(list(df.columns)))
    candidates.sort(key=lambda x:(x[0],x[1]))
    if len(candidates)>1 and candidates[0][0]==candidates[1][0]:
        raise RuntimeError('Ambiguous municipality-name columns in FA25 workbook: '+str([c[1] for c in candidates]))
    name_column=candidates[0][1]
    print('FA25 municipality name column:',name_column,flush=True)
    df['_municipality_name']=candidates[0][2].values

    names={'municipality':{'ALL':'Hela Sverige'},
           'fa':{'ALL':'Hela Sverige'},
           'skr':{'ALL':'Hela Sverige'}}
    for _,r in df.iterrows():
        code=str(r['KommunKod']).strip().zfill(4)
        region=str(r['FA25Nr']).strip()
        municipality=str(r['_municipality_name']).strip()
        region_name=str(r['FA25Namn']).strip()
        if not re.fullmatch(r'\d{4}',code) or not municipality or not region_name:
            raise RuntimeError('Invalid FA25 municipality/region labels: '+str((code,municipality,region,region_name)))
        if code in names['municipality'] and names['municipality'][code]!=municipality:
            raise RuntimeError('Conflicting municipality names for '+code)
        if region in names['fa'] and names['fa'][region]!=region_name:
            raise RuntimeError('Conflicting FA25 region names for '+region)
        names['municipality'][code]=municipality
        names['fa'][region]=region_name

    for code,label in SKR_GROUP_NAMES.items():
        names['skr'][code]=label
    if set(names['municipality'])-{'ALL'}!=set(fa):
        raise RuntimeError('Municipality-name lookup does not cover exactly the FA25 municipalities')
    if set(names['fa'])-{'ALL'}!=set(fa.values()):
        raise RuntimeError('FA25 names do not cover exactly the FA25 regions')
    if set(names['skr'])-{'ALL'}!=set(skr.values()):
        raise RuntimeError('Unexpected SKR groups: '+str(sorted(set(skr.values()))))
    if len(set(names['municipality'].values()))!=291:
        raise RuntimeError('Municipality-name lookup has duplicate visible names')
    return names

def load_pairs(raw):
    z=zipfile.ZipFile(io.BytesIO(raw))
    members=[n for n in z.namelist() if n.lower().endswith('.csv')]
    if not members:raise RuntimeError('SCB bulk ZIP contains no CSV')
    print('CSV members',members[:12])
    member=max(members,key=lambda n:z.getinfo(n).file_size)
    sample=z.read(member)[:3000]
    print('CSV preview',sample[:800].decode('cp1252',errors='replace'))
    for sep in (';',',','\t'):
        try:
            df=pd.read_csv(z.open(member),sep=sep,dtype=str,encoding='cp1252',low_memory=False)
            if df.shape[1]>=4:break
        except Exception:pass
    else:raise RuntimeError('Could not parse SCB CSV')
    print('Columns',list(df.columns),'shape',df.shape)
    columns=list(df.columns)
    def find(*words):
        return next((c for c in columns if all(w in c.lower() for w in words)),None)
    residence=find('bostadskommun')
    workplace=find('arbetsställekommun') or find('arbetskommun')
    year=find('år')
    value=find('sysselsatta') or find('antal')
    sex=find('kön')
    if not all((residence,workplace,year,value)):
        raise RuntimeError('Unexpected SCB header; see printed column names')
    if sex:
        print('Sex labels:',df[sex].dropna().unique()[:12])
        total=df[sex].astype(str).str.lower().str.contains('totalt|samtliga|båda')
        if total.any():df=df.loc[total].copy()
        else:raise RuntimeError('No verified total-sex category: avoid counting men + women twice')
    df['home']=df[residence].map(extract_code)
    df['work']=df[workplace].map(extract_code)
    df['year']=pd.to_numeric(df[year],errors='coerce')
    df['count']=pd.to_numeric(df[value].astype(str).str.replace(' ','',regex=False).str.replace(',','.',regex=False),errors='coerce')
    df=df[df.home.notna() & df.work.notna() & df.year.notna()].copy()
    if df['count'].isna().any():
        raise RuntimeError('Suppressed or missing SCB count in municipality-pair data; cannot assume zero')
    df['count']=df['count'].astype(int)
    df['year']=df['year'].astype(int)
    if df.duplicated(['home','work','year']).any():
        raise RuntimeError('Duplicate municipality pair+year detected; possible hidden sex or measurement dimension')
    if df.year.nunique()<2:raise RuntimeError('Not enough years to study trend')
    return df

def main():
    pairs=load_pairs(download(URLS['commute']))
    fa=load_lookup(URLS['fa'],'fa')
    skr=load_lookup(URLS['skr'],'skr')
    geo_names=load_geo_names(fa,skr)
    codes=set(pairs.home)|set(pairs.work)
    for key,lookup in [('FA25',fa),('SKR2023',skr)]:
        missing=sorted(codes-set(lookup))
        if missing:raise RuntimeError(f'{key} mapping incomplete for {len(missing)} municipality codes: {missing[:20]}')
    pairs['fa_home']=pairs.home.map(fa)
    pairs['fa_work']=pairs.work.map(fa)
    pairs['skr_home']=pairs.home.map(skr)
    pairs['external_count']=pairs['count'].where(pairs.home!=pairs.work,0)
    pairs['cross_fa_count']=pairs['count'].where(pairs.fa_home!=pairs.fa_work,0)
    summary=[]
    def push(group,key,label,sub):
        for year,rows in sub.groupby('year'):
            summary.append(dict(group=group,key=str(key),label=str(label),year=int(year),
               workers=int(rows['count'].sum()),external=int(rows.external_count.sum()),
               cross_fa=int(rows.cross_fa_count.sum())))
    push('municipality','ALL','Hela Sverige',pairs)
    push('skr','ALL','Hela Sverige',pairs)
    push('fa','ALL','Hela Sverige',pairs)
    for code,g in pairs.groupby('home'):push('municipality',code,geo_names['municipality'][code],g)
    for code,g in pairs.groupby('skr_home'):push('skr',code,geo_names['skr'][code],g)
    for code,g in pairs.groupby('fa_home'):push('fa',code,geo_names['fa'][code],g)
    payload=dict(years=sorted(pairs.year.unique().astype(int).tolist()),source=URLS,
        generated_utc=datetime.now(timezone.utc).isoformat(),records=int(len(pairs)),summary=summary)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    LABELS_OUT.write_text(json.dumps({'source':URLS['fa'],'names':geo_names},ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n',encoding='utf-8')
    print('Successfully generated',len(summary),'summary rows')
if __name__=='__main__':main()
