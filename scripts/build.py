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
    return best[5]

def load_pairs(raw):
    z=zipfile.ZipFile(io.BytesIO(raw))
    members=[n for n in z.namelist() if n.lower().endswith('.csv')]
    if not members:raise RuntimeError('SCB bulk ZIP contains no CSV')
    print('CSV members',members[:12])
    member=max(members,key=lambda n:z.getinfo(n).file_size)
    sample=z.read(member)[:3000]
    print('CSV preview',sample[:800].decode('utf-8-sig',errors='replace'))
    for sep in (';',',','\t'):
        try:
            df=pd.read_csv(z.open(member),sep=sep,dtype=str,encoding='utf-8-sig',low_memory=False)
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
    for code,g in pairs.groupby('home'):push('municipality',code,code,g)
    for code,g in pairs.groupby('skr_home'):push('skr',code,code,g)
    for code,g in pairs.groupby('fa_home'):push('fa',code,code,g)
    payload=dict(years=sorted(pairs.year.unique().astype(int).tolist()),source=URLS,
        generated_utc=datetime.now(timezone.utc).isoformat(),records=int(len(pairs)),summary=summary)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    print('Successfully generated',len(summary),'summary rows')
if __name__=='__main__':main()
