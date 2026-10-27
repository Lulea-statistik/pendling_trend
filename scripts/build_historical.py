"""Historical cross-municipality commuter series (RAMS); no fabricated denominators.

Sources: TAB333 2004-2018, TAB5850 2019-2021, TAB3266 aggregate
cross-check. BAS series remains separate because concepts/methods differ.
"""
import io,json,re,zipfile
from pathlib import Path
from datetime import datetime,timezone
import pandas as pd,requests

BASE=Path(__file__).resolve().parent.parent
ROOT='https://www.statistikdatabasen.scb.se/Resources/PX/bulk/ssd/sv/'
SOURCES={'rams_2004_2018':'TAB333_sv.zip','rams_2019_2021':'TAB5850_sv.zip',
         'rams_aggregate_2004_2018':'TAB3266_sv.zip'}
def get_frame(code):
    r=requests.get(ROOT+code,timeout=240);r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.csv')]
        if len(names)!=1:raise RuntimeError(f'Expected one CSV in {code}: {names}')
        raw=z.read(names[0])
    frame=None
    for enc in ['cp1252','utf-8-sig']:
        try:
            frame=pd.read_csv(io.BytesIO(raw),encoding=enc,dtype=str,low_memory=False)
            break
        except UnicodeDecodeError:continue
    if frame is None:raise RuntimeError('Unknown encoding '+code)
    print(code,frame.shape,frame.columns.tolist(),flush=True)
    return frame

def field(df,needle):
    v=[c for c in df if c.lower().strip()==needle]
    if not v: v=[c for c in df if needle in c.lower()]
    if len(v)!=1:raise ValueError(f'Expected column matching {needle}, found {v}')
    return v[0]
def code(s):
    m=re.match(r'^(\d{4})(?:\D|$)',str(s).strip())
    return m.group(1) if m else None

def pairs(df,source,year_start,year_end,fa,skr):
    h=field(df,'bostadskommun')
    w=field(df,'arbetsställekommun')
    y=field(df,'år')
    v=next((c for c in df if 'pendlare' in c.lower() and c not in (h,w)),None)
    if not v:raise ValueError(f'No pendlare measure in {source}: {df.columns.tolist()}')
    sex=field(df,'kön')
    sel=df[sex].astype(str).str.lower().str.strip().isin(['totalt','män och kvinnor'])
    if not sel.any():raise ValueError(f'No total sex in {source}: {df[sex].unique()}')
    df=df.loc[sel,[h,w,y,v]].copy()
    df['home']=df[h].map(code);df['work']=df[w].map(code)
    df['year']=pd.to_numeric(df[y],errors='coerce')
    df['count']=pd.to_numeric(df[v].str.strip(),errors='coerce')
    if df[['home','work','year','count']].isna().any().any():
        raise RuntimeError(f'Unexpected municipality key or suppressed count in {source}')
    df['year']=df.year.astype(int)
    if df.year.min()!=year_start or df.year.max()!=year_end:
        raise RuntimeError(f'Unexpected years in {source}: {sorted(df.year.unique())}')
    # SCB municipality-pair tables also include people working in their home municipality.
    # These are valid observations, but not cross-municipality commuters.
    same=df.home==df.work
    print(source,'within-municipality observations:',int(same.sum()),
          'workers:',int(df.loc[same,'count'].sum()),flush=True)
    if df.empty:
        raise RuntimeError('Historical municipality-pair table is empty')
    if df.duplicated(['home','work','year']).any():raise RuntimeError('Duplicate historical OD-year')
    if not (set(df.home)|set(df.work)).issubset(set(fa)&set(skr)):
        raise RuntimeError('Historical municipality codes not fully covered by classifications')
    df['fa_home']=df.home.map(fa);df['fa_work']=df.work.map(fa);df['skr_home']=df.home.map(skr)
    df['external_count']=df['count'].where(df.home!=df.work,0)
    df['cross_fa_count']=df['external_count'].where(df.fa_home!=df.fa_work,0)
    result=[]
    def append(group,key,label,part):
        for year,g in part.groupby('year'):
            result.append(dict(group=group,key=str(key),label=str(label),year=int(year),
               external=int(g.external_count.sum()),cross_fa=int(g.cross_fa_count.sum()),
               workers=int(g['count'].sum()),source=source))
    for grp in ('municipality','skr','fa'):append(grp,'ALL','Hela Sverige',df)
    for key,g in df.groupby('home'):append('municipality',key,key,g)
    for key,g in df.groupby('skr_home'):append('skr',key,key,g)
    for key,g in df.groupby('fa_home'):append('fa',key,key,g)
    return result

def main():
    from build import load_lookup,URLS
    fa=load_lookup(URLS['fa'],'fa');skr=load_lookup(URLS['skr'],'skr')
    result=[]
    for source,start,end in [('rams_2004_2018',2004,2018),('rams_2019_2021',2019,2021)]:
        result+=pairs(get_frame(SOURCES[source]),source,start,end,fa,skr)
    # Aggregate source is retained and checked for column presence and years;
    # it is not added to municipality-pair totals (would double-count).
    agg=get_frame(SOURCES['rams_aggregate_2004_2018'])
    required={'region','kön','år','tabellinnehåll'}
    if not required.issubset(agg.columns):
        raise RuntimeError('Missing aggregate dimensions: '+str(sorted(required-set(agg.columns))))
    categories=agg['tabellinnehåll'].dropna().astype(str).str.strip()
    print('TAB3266 tabellinnehåll categories:',sorted(categories.unique().tolist()),flush=True)
    if categories.empty or not categories.str.contains('pendl|arbet|kommun',case=False,regex=True).any():
        raise RuntimeError('TAB3266 aggregate categories are empty or unexpected')
    valcols=[c for c in agg.columns if c not in required]
    if len(valcols)!=1:
        raise RuntimeError('TAB3266 expected one measure column, got '+str(valcols))
    years=pd.to_numeric(agg['år'],errors='coerce')
    if years.isna().any() or years.min()>2004 or years.max()<2018:
        raise RuntimeError('TAB3266 aggregate year coverage differs from expected 2004-2018')
    totalmask=agg['kön'].astype(str).str.strip().str.lower().isin(['män och kvinnor','totalt'])
    if not totalmask.any():
        raise RuntimeError('TAB3266 missing combined sex category')
    values=pd.to_numeric(agg.loc[totalmask,valcols[0]],errors='coerce')
    print('TAB3266 total-sex rows:',int(totalmask.sum()),'numeric:',int(values.notna().sum()),flush=True)
    if values.notna().sum()==0:
        raise RuntimeError('TAB3266 lacks numeric aggregated observations')
    output=BASE/'docs/data/historical.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({'rows':result,'years':list(range(2004,2022)),
        'sources':{k:ROOT+v for k,v in SOURCES.items()},
        'generated_utc':datetime.now(timezone.utc).isoformat()},
        ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    print('Historical summary rows',len(result))
if __name__=='__main__':main()
