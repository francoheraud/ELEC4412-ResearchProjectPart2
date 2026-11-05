"""Paper-size graph exports from saved branch tables; no model fitting."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch
from matplotlib.lines import Line2D

LABELS={
 'unrestricted_2R1C_wall':'Unrestricted 2R1C',
 'local_1R_wall':'1R: restricted connectivity',
 'local_2R1C_wall':'Restricted 2R1C (air + wall priors)',
 'local_3R2C_wall':'Restricted 3R2C (air + wall priors)',
 'local_2R1C_free_air':'2R1C: estimated air capacitances',
 'local_2R1C_air_only':'2R1C: fixed air capacitances',
 'unrestricted':'Unrestricted interzone and plenum connections',
 'local_plenums':'Same-floor connections + local plenums (1R)',
 'local_with_slab':'Same-floor connections + local plenums (slab storage)',
}
SLUGS={'local_1R_wall':'1R','local_2R1C_wall':'2R1C','local_3R2C_wall':'3R2C',
       'local_2R1C_free_air':'free_air','local_2R1C_air_only':'air_only',
       'unrestricted_2R1C_wall':'unrestricted','unrestricted':'unrestricted',
       'local_plenums':'local_plenums','local_with_slab':'local_slab'}
BLUE='#006b83'; ORANGE='#bd6400'; PINK='#9b457e'

def truth(value):return str(value).lower()=='true'

def positions():
    pos={};labels={}
    for f,tag in enumerate(['BOT','MID','TOP']):
        core=['CORE_BOTTOM','CORE_MID','CORE_TOP'][f]
        pos[core]=(0,3*f);labels[core]='Core '+['B','M','T'][f]
        for k,(x,y) in enumerate([(0,-.9),(1.15,0),(0,.9),(-1.15,0)],1):
            z=f'PERIMETER_{tag}_ZN_{k}';pos[z]=(x,3*f+y);labels[z]=f'P_{["B","M","T"][f]}{k}'
        p=['FIRSTFLOOR_PLENUM','MIDFLOOR_PLENUM','TOPFLOOR_PLENUM'][f]
        pos[p]=(2.6,3*f+.9);labels[p]=f'Plenum {f+1}'
    return pos,labels

def draw_panel(ax,frame,candidate):
    pos,labels=positions()
    f=frame[frame.kind.eq('interzone')|frame.kind.str.startswith('plenum')]
    if not candidate:f=f[f.retained.map(truth)]
    # Draw boundary paths first, so retained interzone connections remain visible.
    f=f.assign(_inter=f.kind.eq('interzone')).sort_values('_inter')
    for row in f.itertuples():
        a,b=pos[row.node_i],pos[row.node_j];inter=row.kind=='interzone'
        color=('#708598' if candidate else BLUE if truth(row.direct_IDF_adjacency) else ORANGE) if inter else PINK
        rad=.09 if inter else .045
        # Opposing perimeter paths must not appear to connect through the core.
        if inter and (abs(a[0]-b[0])<.01 or abs(a[1]-b[1])<.01) and np.linalg.norm(np.subtract(a,b))>1.4:rad=.36
        ax.add_patch(FancyArrowPatch(a,b,arrowstyle='-',connectionstyle=f'arc3,rad={rad}',
            shrinkA=4,shrinkB=5,color=color,lw=(.75 if candidate else 1.55 if inter else 1.05),
            alpha=(.40 if candidate else .96 if inter else .72),
            linestyle='--' if not inter and row.branch_order!='1R' else '-',zorder=1 if not inter else 2))
    for node,point in pos.items():
        plenum=node.endswith('PLENUM')
        ax.scatter(*point,s=95 if plenum else 48,marker='s' if plenum else 'o',
            facecolor='#f4dce9' if plenum else '#deebf6',edgecolor=PINK if plenum else '#315876',linewidths=.9,zorder=4)
        ax.annotate(labels[node],point,xytext=(0,9 if plenum else 6),textcoords='offset points',
            ha='center',va='bottom',fontsize=9.5,fontweight='medium',zorder=5,
            bbox=dict(facecolor='white',edgecolor='none',alpha=.86,pad=.25))
    inter=int(f.kind.eq('interzone').sum());plenum=len(f)-inter
    ax.set_title(('Candidate graph' if candidate else 'Retained graph')+f'\n{inter} interzone; {plenum} plenum',fontsize=10,pad=4)
    ax.set_xlim(-1.65,3.45);ax.set_ylim(-1.1,8.0);ax.axis('off')
    return dict(interzone=inter,plenum=plenum)

def render(names,params,rule,path):
    # Width is close to an A4 report's 17 cm text block, avoiding font shrinkage.
    count=len(names);height=4.1*count+.75
    with plt.rc_context({'font.family':'DejaVu Sans','pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none'}):
        fig=plt.figure(figsize=(6.7,height))
        outer=fig.add_gridspec(count,1,left=.025,right=.98,bottom=.80/height,top=1-.12/height,hspace=.09)
        audit=[]
        for r,name in enumerate(names):
            inner=outer[r].subgridspec(2,2,height_ratios=[.32,3.45],hspace=.27,wspace=.14)
            title=fig.add_subplot(inner[0,:]);title.axis('off')
            title.text(.5,.55,LABELS[name],ha='center',va='center',fontsize=11,fontweight='bold')
            frame=params[(params.case==name)&(params.selection==rule)]
            assert len(frame)>0,name
            for c in range(2):
                ax=fig.add_subplot(inner[1,c]);audit.append(dict(model=name,candidate=c==0,**draw_panel(ax,frame,c==0)))
        handles=[Line2D([0],[0],color=BLUE,lw=1.6,label='Shared-wall interzone'),
                 Line2D([0],[0],color=ORANGE,lw=1.6,label='Other interzone'),
                 Line2D([0],[0],color=PINK,lw=1.2,label='Plenum: 1R'),
                 Line2D([0],[0],color=PINK,lw=1.2,ls='--',label='Plenum: storage')]
        fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.5,.32/height),ncol=2,fontsize=8.5,frameon=False,
                   columnspacing=1.4,handlelength=2.2)
        fig.text(.5,.16/height,'B/M/T: bottom/middle/top floor. Plenums are prescribed inputs.\nStorage branches shown as single paths; outdoor/ground paths omitted.',
                 ha='center',va='center',fontsize=8)
        for ext in ['pdf','svg','png']:fig.savefig(Path(path).with_suffix('.'+ext),dpi=300,facecolor='white')
        plt.close(fig)
    return audit

def graph_figure(data,names,cases,params,rule,path):
    """Drop-in replacement for both existing matched report generators."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    audits={path.name:render(names,params,rule,path)}
    if len(names)>2:
        groups=[names[:2],names[2:]]
        pages=[]
        for group in groups:
            suffix='_'.join(SLUGS[n] for n in group)
            target=path.with_name(path.name+'_'+suffix)
            audits[target.name]=render(group,params,rule,target);pages.append(target.name+'.png')
    else:pages=[path.name+'.png']
    # Individual rows are useful for columns, presentations or tighter page layouts.
    for name in names:
        target=path.with_name(path.name+'_'+SLUGS[name])
        if target.name not in audits:audits[target.name]=render([name],params,rule,target)
    manifest=path.parent/'graph_pages.json'
    content=json.loads(manifest.read_text()) if manifest.exists() else {}
    content[rule]=pages;manifest.write_text(json.dumps(content,indent=2))
    (path.parent/(path.name+'_drawing_audit.json')).write_text(json.dumps(audits,indent=2))
    return audits

def plot_legacy(zones,pn,realpairs,edges,params,boundary,slabparams,figs):
    def floor(z):return next(i for i,tag in enumerate(['BOT','MID','TOP']) if tag in z)
    rows=[];slab=pd.DataFrame(slabparams)
    for config in ['unrestricted','local_plenums','local_with_slab']:
        label=config+'_best_accuracy'
        selected=slab[slab.model.eq('slab_best_accuracy')] if config=='local_with_slab' else None
        p=params[params.model.eq(label)] if selected is None else None
        b=boundary[boundary.model.eq(label)] if selected is None else None
        for i,j in edges:
            if config!='unrestricted' and floor(zones[i])!=floor(zones[j]):continue
            match=selected[(selected.node_i==zones[i])&(selected.node_j==zones[j])] if selected is not None else p[(p.zone_i==zones[i])&(p.zone_j==zones[j])]
            retained=bool(len(match) and (selected is not None or truth(match.iloc[0].retained)))
            adjacent=bool(len(match) and truth(match.iloc[0].direct_IDF_adjacency))
            rows.append(dict(case=config,selection='best_accuracy',node_i=zones[i],node_j=zones[j],kind='interzone',branch_order='2R1C',retained=retained,direct_IDF_adjacency=adjacent))
        for z in zones:
            for pl in pn:
                if config!='unrestricted' and (z,pl) not in realpairs:continue
                match=selected[(selected.node_i==z)&(selected.node_j==pl)] if selected is not None else b[(b.zone==z)&(b.boundary==pl)]
                retained=bool(len(match) and match.iloc[0].G_kW_K>1e-6)
                storage=config=='local_with_slab' and floor(z)>0 and pl==pn[floor(z)-1]
                rows.append(dict(case=config,selection='best_accuracy',node_i=z,node_j=pl,kind='plenum_lower' if storage else 'plenum_upper_or_remote',branch_order='2R1C' if storage else '1R',retained=retained,direct_IDF_adjacency=False))
    return graph_figure(None,['unrestricted','local_plenums','local_with_slab'],None,pd.DataFrame(rows),'best_accuracy',Path(figs)/'graphs_with_plenums')
