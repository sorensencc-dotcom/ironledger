/* @ds-bundle: {"format":4,"namespace":"CastIronCharlieDesignSystem_019de1","components":[{"name":"ArchivePage","sourcePath":"ui_kits/website/ArchivePage.jsx"},{"name":"HookSection","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"StorySection","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"WillysSection","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"WhyNowSection","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"TimelineSection","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"PressSection","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"ContactSection","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"Footer","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"ContentSections","sourcePath":"ui_kits/website/ContentSections.jsx"},{"name":"Hero","sourcePath":"ui_kits/website/Hero.jsx"},{"name":"Nav","sourcePath":"ui_kits/website/Nav.jsx"},{"name":"SectionLabel","sourcePath":"ui_kits/website/SectionComponents.jsx"},{"name":"GradientRule","sourcePath":"ui_kits/website/SectionComponents.jsx"},{"name":"PullQuote","sourcePath":"ui_kits/website/SectionComponents.jsx"},{"name":"StatBlock","sourcePath":"ui_kits/website/SectionComponents.jsx"},{"name":"Tag","sourcePath":"ui_kits/website/SectionComponents.jsx"},{"name":"StatusBadge","sourcePath":"ui_kits/website/SectionComponents.jsx"},{"name":"SectionInner","sourcePath":"ui_kits/website/SectionComponents.jsx"},{"name":"SectionComponents","sourcePath":"ui_kits/website/SectionComponents.jsx"}],"sourceHashes":{"ui_kits/website/ArchivePage.jsx":"ab797c423958","ui_kits/website/ContentSections.jsx":"acbb26bfe520","ui_kits/website/Hero.jsx":"c4b435575233","ui_kits/website/Nav.jsx":"902fe06a6bfc","ui_kits/website/SectionComponents.jsx":"21d33cd1dbfc"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.CastIronCharlieDesignSystem_019de1 = window.CastIronCharlieDesignSystem_019de1 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// ui_kits/website/ArchivePage.jsx
try { (() => {
// ArchivePage.jsx — Cast Iron Charlie research archive portal
// Password-gated collections with photo series grid

const COLLECTIONS = [{
  id: 'mfm',
  status: 'live',
  institution: 'Michigan Flight Museum',
  title: 'Ford Motor Company Photographic Archive',
  desc: 'Ford wartime production photography, 1941–1943. VIP visits, Willow Run construction and operation, B-24 production. Includes 7 catalog corrections.',
  stats: [{
    n: '19',
    l: 'Series'
  }, {
    n: '49',
    l: 'Files'
  }, {
    n: '7',
    l: 'Corrections',
    accent: true
  }]
}, {
  id: 'kroll',
  status: 'live',
  institution: 'Mike Kroll Research',
  title: 'Press, Trade & Archival Finds',
  desc: 'Key photographic and documentary discoveries — press portraits, Fortune coverage, resignation-era trade press, and the rarest known Ford executive group portrait.',
  stats: [{
    n: '6',
    l: 'Key Finds'
  }, {
    n: '400+',
    l: 'Items'
  }, {
    n: 'Tier 1',
    l: 'Sources',
    accent: true
  }]
}, {
  id: 'bgsu',
  status: 'soon',
  institution: 'Bowling Green State University',
  title: 'M/Y Helene & Nautical Materials',
  desc: 'Photographs of the Sorensen yacht M/Y Helene (Bath Iron Works, 1931) and related nautical materials sourced through Mark Sprang.',
  stats: [{
    n: '—',
    l: 'Pending'
  }]
}, {
  id: 'thf',
  status: 'soon',
  institution: 'The Henry Ford / Benson Ford Research Center',
  title: 'Ford Corporate Archive',
  desc: 'Primary Ford Motor Company corporate records, executive correspondence, and production documentation held at The Henry Ford in Dearborn.',
  stats: [{
    n: '—',
    l: 'Pending'
  }]
}];
const SERIES = [{
  id: '75901',
  tags: ['high', 'willow-run'],
  date: '2-24-41 · 3 variants',
  title: 'Pratt & Whitney Engine Test Facility',
  subjects: 'C.E. Sorensen (tall, pinstripe, pointing), Edsel Ford, Mead Bricker. Variant D: full instrumented control room.',
  variants: ['A', 'B', 'D · Control Room']
}, {
  id: '75904',
  tags: ['high', 'willow-run'],
  date: 'c. 1941 · 3 variants',
  title: 'Willow Run Scale Model — Architectural Review',
  subjects: 'Four unidentified men consulting over model. 75904-C: aerial close-up with miniature figure for scale — the documentary standout.',
  variants: ['A · Men at Model', 'Unlabeled', '★ Aerial Close-Up'],
  keyIdx: 2
}, {
  id: '76165',
  tags: ['high'],
  date: '10-2-41 · 1 variant',
  title: 'Portrait of C.E. Sorensen',
  subjects: 'Confirmed: C.E. Sorensen. Formal studio portrait — fair-haired, pinstripe suit, pocket square.',
  variants: ['Studio Portrait']
}, {
  id: '76225',
  tags: ['high', 'vip'],
  date: '10-13-41 · 4 variants',
  title: 'Sperry Gyroscope — Bombsight Inspection',
  subjects: 'C.E. Sorensen prominent in 01 & 03. Group examining the Sperry bombsight — critical wartime targeting technology.',
  variants: ['01', '02', '03', '04']
}, {
  id: '76632',
  tags: ['high', 'new'],
  date: 'Undated · 1 variant',
  title: 'C.E. Sorensen — Solo Engine Portrait',
  subjects: 'Rare intimate solo portrait — Sorensen working hands-on with a radial aircraft engine, suit on. Not in original catalog.',
  variants: ['★ New Find'],
  keyIdx: 0
}, {
  id: '76707',
  tags: ['high', 'vip', 'willow-run'],
  date: '4-13-42 · 1 variant',
  title: 'Sen. Harry Truman Visits Willow Run',
  subjects: 'Sen. Harry Truman (4th from left), Edsel Ford (5th), C.E. Sorensen (6th). Plant still under construction.',
  variants: ['Group Visit']
}];
const tagConfig = {
  high: {
    label: 'High Priority',
    color: '#C4501A',
    border: 'rgba(196,80,26,0.45)',
    bg: 'rgba(196,80,26,0.07)'
  },
  medium: {
    label: 'Medium Priority',
    color: '#7a9fbf',
    border: 'rgba(122,159,191,0.4)',
    bg: 'rgba(122,159,191,0.07)'
  },
  new: {
    label: 'New Find',
    color: '#B8922A',
    border: 'rgba(184,146,42,0.45)',
    bg: 'rgba(184,146,42,0.07)'
  },
  'willow-run': {
    label: 'Willow Run',
    color: '#9a9088',
    border: 'rgba(154,144,136,0.25)',
    bg: 'transparent'
  },
  vip: {
    label: 'VIP Visit',
    color: '#9a9088',
    border: 'rgba(154,144,136,0.25)',
    bg: 'transparent'
  },
  corrected: {
    label: 'Corrected ID',
    color: '#C4501A',
    border: 'rgba(196,80,26,0.35)',
    bg: 'transparent'
  }
};
const SeriesTag = ({
  t
}) => {
  const c = tagConfig[t] || tagConfig.high;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.6rem',
      fontWeight: 600,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      padding: '0.2rem 0.6rem',
      border: `1px solid ${c.border}`,
      background: c.bg,
      color: c.color,
      display: 'inline-block'
    }
  }, c.label);
};
const PhotoPlaceholder = ({
  id,
  variant,
  isKey
}) => /*#__PURE__*/React.createElement("div", {
  style: {
    width: '100%',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.4rem'
  }
}, /*#__PURE__*/React.createElement("span", {
  style: {
    fontFamily: "'Barlow Condensed', sans-serif",
    fontWeight: 800,
    fontSize: '1.3rem',
    letterSpacing: '0.08em',
    color: isKey ? 'rgba(184,146,42,0.5)' : 'rgba(154,144,136,0.25)'
  }
}, id), /*#__PURE__*/React.createElement("span", {
  style: {
    fontFamily: "'Barlow Condensed', sans-serif",
    fontSize: '0.58rem',
    letterSpacing: '0.2em',
    textTransform: 'uppercase',
    color: isKey ? 'rgba(184,146,42,0.4)' : 'rgba(154,144,136,0.2)'
  }
}, variant));
const PasswordModal = ({
  collection,
  onSuccess,
  onClose
}) => {
  const [pw, setPw] = React.useState('');
  const [error, setError] = React.useState('');
  const check = () => {
    // Demo: any non-empty input grants access
    if (pw.trim().length > 0) {
      onSuccess(collection);
    } else {
      setError('Incorrect access code. Try again.');
      setTimeout(() => setError(''), 2000);
    }
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      background: 'rgba(10,8,6,0.92)',
      zIndex: 400,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '2rem'
    },
    onClick: e => e.target === e.currentTarget && onClose()
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#1a1410',
      border: '1px solid rgba(154,144,136,0.15)',
      padding: '3rem',
      maxWidth: 420,
      width: '100%',
      position: 'relative'
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: onClose,
    style: {
      position: 'absolute',
      top: '1rem',
      right: '1rem',
      background: 'transparent',
      border: '1px solid rgba(154,144,136,0.2)',
      color: '#9a9088',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.65rem',
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      padding: '0.35rem 0.8rem',
      cursor: 'pointer'
    }
  }, "\u2715 Close"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.65rem',
      fontWeight: 600,
      letterSpacing: '0.4em',
      textTransform: 'uppercase',
      color: '#C4501A',
      marginBottom: '1.5rem'
    }
  }, "Cast Iron Charlie \xB7 Documentary Research Portal"), /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 900,
      fontSize: '2rem',
      color: '#faf6f0',
      marginBottom: '0.5rem',
      lineHeight: 1.1
    }
  }, "Cast Iron Charlie", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "Research Archive")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.82rem',
      lineHeight: 1.8,
      color: '#9a9088',
      fontStyle: 'italic',
      marginBottom: '1.5rem'
    }
  }, "Charles Emil Sorensen spent four decades as Henry Ford's most trusted lieutenant \u2014 the man who turned the moving assembly line from idea into industrial reality."), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 40,
      height: 1,
      background: '#C4501A',
      marginBottom: '2rem'
    }
  }), /*#__PURE__*/React.createElement("label", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.65rem',
      fontWeight: 600,
      letterSpacing: '0.35em',
      textTransform: 'uppercase',
      color: '#9a9088',
      display: 'block',
      marginBottom: '0.5rem'
    }
  }, "Access Code"), /*#__PURE__*/React.createElement("input", {
    type: "password",
    value: pw,
    onChange: e => setPw(e.target.value),
    onKeyDown: e => e.key === 'Enter' && check(),
    placeholder: "Enter access code",
    autoComplete: "off",
    style: {
      width: '100%',
      background: 'rgba(10,8,6,0.8)',
      border: `1px solid ${error ? '#C4501A' : 'rgba(154,144,136,0.2)'}`,
      color: '#faf6f0',
      padding: '0.9rem 1rem',
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.9rem',
      outline: 'none',
      marginBottom: '0.5rem',
      boxSizing: 'border-box'
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      letterSpacing: '0.15em',
      color: '#C4501A',
      minHeight: '1.2em',
      marginBottom: '1rem'
    }
  }, error || '\u00a0'), /*#__PURE__*/React.createElement("button", {
    onClick: check,
    style: {
      width: '100%',
      background: '#C4501A',
      border: 'none',
      color: '#0a0806',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '0.85rem',
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      padding: '1rem',
      cursor: 'pointer'
    }
  }, "Enter \u2192"), /*#__PURE__*/React.createElement("p", {
    style: {
      marginTop: '1.5rem',
      textAlign: 'center'
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: "mailto:info@castironcharlie.com",
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#9a9088',
      textDecoration: 'none',
      borderBottom: '1px solid rgba(154,144,136,0.3)',
      paddingBottom: 2
    }
  }, "Request Access \u2192"))));
};
const FILTERS = [{
  id: 'all',
  label: 'All Series'
}, {
  id: 'high',
  label: 'High Priority'
}, {
  id: 'corrected',
  label: 'Corrected IDs'
}, {
  id: 'new',
  label: 'New Finds'
}, {
  id: 'willow-run',
  label: 'Willow Run'
}, {
  id: 'vip',
  label: 'VIP Visits'
}];
const MFMCollection = () => {
  const [activeFilter, setActiveFilter] = React.useState('all');
  const [lightbox, setLightbox] = React.useState(null);
  const filtered = SERIES.filter(s => activeFilter === 'all' || s.tags.includes(activeFilter));
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '5rem 0 4rem',
      background: '#2c2420',
      borderBottom: '1px solid rgba(139,58,26,0.15)',
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: -4,
      top: '50%',
      transform: 'translateY(-50%)',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 800,
      fontSize: '14rem',
      lineHeight: 1,
      color: 'rgba(139,58,26,0.04)',
      pointerEvents: 'none',
      whiteSpace: 'nowrap'
    }
  }, "MFM"), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1100,
      margin: '0 auto',
      padding: '0 4rem',
      position: 'relative',
      zIndex: 1
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, null, "Michigan Flight Museum \xB7 Ford Motor Company Collection"), /*#__PURE__*/React.createElement("h2", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 900,
      fontSize: 'clamp(2rem,5vw,4rem)',
      lineHeight: 1.05,
      color: '#faf6f0',
      marginBottom: '2.5rem'
    }
  }, "The Sorensen", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "Photographic Archive")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: '3rem',
      marginBottom: '1.5rem',
      paddingBottom: '1.5rem',
      borderBottom: '1px solid rgba(154,144,136,0.12)'
    }
  }, [['Photo Series', '19'], ['Total Files', '49'], ['Date Range', 'Oct 1941 – Sept 1943'], ['Catalog Corrections', '7'], ['Institutional Contact', 'Julie Osborne, MFM']].map(([l, v]) => /*#__PURE__*/React.createElement("div", {
    key: l
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.6rem',
      letterSpacing: '0.35em',
      textTransform: 'uppercase',
      color: '#C4501A',
      marginBottom: '0.2rem'
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '1rem',
      fontWeight: 600,
      color: '#faf6f0',
      letterSpacing: '0.05em'
    }
  }, v)))), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.95rem',
      color: '#e8e0d4',
      lineHeight: 1.85,
      fontStyle: 'italic',
      maxWidth: 680
    }
  }, "Ford Motor Company archive photographs documenting C.E. Sorensen's central role in wartime production. Seven original catalog descriptions have been corrected through cross-reference research."))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#2c2420',
      borderBottom: '1px solid rgba(154,144,136,0.1)',
      position: 'sticky',
      top: 72,
      zIndex: 90
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1100,
      margin: '0 auto',
      padding: '1rem 4rem',
      display: 'flex',
      alignItems: 'center',
      gap: '0.5rem',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.62rem',
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      color: '#9a9088',
      marginRight: '0.5rem'
    }
  }, "Filter"), FILTERS.map(f => /*#__PURE__*/React.createElement("button", {
    key: f.id,
    onClick: () => setActiveFilter(f.id),
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.72rem',
      fontWeight: 600,
      letterSpacing: '0.15em',
      textTransform: 'uppercase',
      background: activeFilter === f.id ? 'rgba(196,80,26,0.08)' : 'transparent',
      border: `1px solid ${activeFilter === f.id ? '#C4501A' : 'rgba(154,144,136,0.2)'}`,
      color: activeFilter === f.id ? '#C4501A' : '#9a9088',
      padding: '0.4rem 1rem',
      cursor: 'pointer',
      transition: 'all 0.2s'
    }
  }, f.label)))), filtered.map((series, si) => /*#__PURE__*/React.createElement("div", {
    key: series.id,
    style: {
      background: si % 2 === 0 ? '#0a0806' : '#1a1410',
      borderBottom: '1px solid rgba(154,144,136,0.1)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1100,
      margin: '0 auto',
      padding: '4rem'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 120px',
      gap: '2rem',
      alignItems: 'start',
      marginBottom: '2rem'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: '0.5rem',
      marginBottom: '0.75rem'
    }
  }, series.tags.map(t => /*#__PURE__*/React.createElement(SeriesTag, {
    key: t,
    t: t
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.6rem',
      fontWeight: 600,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      padding: '0.2rem 0.6rem',
      border: '1px solid rgba(154,144,136,0.25)',
      color: '#9a9088'
    }
  }, series.date)), /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 700,
      fontSize: 'clamp(1.3rem,2.5vw,1.9rem)',
      color: '#faf6f0',
      lineHeight: 1.2,
      marginBottom: '0.75rem'
    }
  }, series.title), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.95rem',
      color: '#e8e0d4',
      lineHeight: 1.8,
      marginBottom: '0.5rem'
    }
  }, series.subjects)), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 900,
      fontStyle: 'italic',
      fontSize: '4rem',
      lineHeight: 1,
      color: 'rgba(139,58,26,0.15)',
      textAlign: 'right',
      paddingTop: '0.2rem'
    }
  }, series.id)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
      gap: '0.6rem'
    }
  }, series.variants.map((v, vi) => {
    const isKey = series.keyIdx === vi;
    return /*#__PURE__*/React.createElement("div", {
      key: v,
      onClick: () => setLightbox({
        series,
        variantIdx: vi
      }),
      style: {
        position: 'relative',
        background: '#2c2420',
        cursor: 'pointer',
        aspectRatio: '4/3',
        overflow: 'hidden',
        border: `1px solid ${isKey ? 'rgba(184,146,42,0.35)' : 'rgba(154,144,136,0.12)'}`,
        transition: 'border-color 0.3s'
      },
      onMouseEnter: e => {
        e.currentTarget.style.borderColor = 'rgba(196,80,26,0.5)';
      },
      onMouseLeave: e => {
        e.currentTarget.style.borderColor = isKey ? 'rgba(184,146,42,0.35)' : 'rgba(154,144,136,0.12)';
      }
    }, /*#__PURE__*/React.createElement(PhotoPlaceholder, {
      id: series.id,
      variant: v,
      isKey: isKey
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        position: 'absolute',
        inset: 0,
        background: 'linear-gradient(to top, rgba(10,8,6,0.88) 0%, transparent 55%)',
        opacity: 0,
        transition: 'opacity 0.25s',
        display: 'flex',
        alignItems: 'flex-end',
        padding: '0.8rem'
      },
      onMouseEnter: e => e.currentTarget.style.opacity = 1,
      onMouseLeave: e => e.currentTarget.style.opacity = 0
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "'Barlow Condensed', sans-serif",
        fontSize: '0.65rem',
        fontWeight: 700,
        letterSpacing: '0.2em',
        textTransform: 'uppercase',
        color: '#B8922A'
      }
    }, series.id, "-", v)));
  }))))), lightbox && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      background: 'rgba(10,8,6,0.97)',
      zIndex: 600,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '2rem'
    },
    onClick: () => setLightbox(null)
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 360px',
      gap: '3rem',
      maxWidth: 1100,
      width: '100%',
      maxHeight: '88vh'
    },
    onClick: e => e.stopPropagation()
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#2c2420',
      border: '1px solid rgba(154,144,136,0.12)',
      overflow: 'hidden',
      maxHeight: '80vh'
    }
  }, /*#__PURE__*/React.createElement(PhotoPlaceholder, {
    id: lightbox.series.id,
    variant: lightbox.series.variants[lightbox.variantIdx],
    isKey: lightbox.series.keyIdx === lightbox.variantIdx
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      overflowY: 'auto'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 900,
      fontStyle: 'italic',
      fontSize: '3.5rem',
      lineHeight: 1,
      color: 'rgba(139,58,26,0.2)',
      marginBottom: '0.5rem'
    }
  }, lightbox.series.id), /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 700,
      fontSize: '1.25rem',
      color: '#faf6f0',
      lineHeight: 1.3,
      marginBottom: '1rem'
    }
  }, lightbox.series.title), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: '0.4rem',
      marginBottom: '1.5rem'
    }
  }, lightbox.series.tags.map(t => /*#__PURE__*/React.createElement(SeriesTag, {
    key: t,
    t: t
  }))), [['Variant', lightbox.series.variants[lightbox.variantIdx]], ['Date', lightbox.series.date], ['Subjects', lightbox.series.subjects]].map(([l, v]) => /*#__PURE__*/React.createElement("div", {
    key: l,
    style: {
      marginBottom: '1.25rem',
      paddingBottom: '1.25rem',
      borderBottom: '1px solid rgba(154,144,136,0.1)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.6rem',
      fontWeight: 600,
      letterSpacing: '0.35em',
      textTransform: 'uppercase',
      color: '#C4501A',
      marginBottom: '0.4rem'
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.88rem',
      color: '#e8e0d4',
      lineHeight: 1.65
    }
  }, v))))), /*#__PURE__*/React.createElement("button", {
    onClick: () => setLightbox(null),
    style: {
      position: 'fixed',
      top: '1.5rem',
      right: '1.5rem',
      background: 'transparent',
      border: '1px solid rgba(154,144,136,0.3)',
      color: '#9a9088',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      padding: '0.5rem 1rem',
      cursor: 'pointer'
    }
  }, "\u2715 Close")));
};
function ArchivePage({
  onNavigate
}) {
  const [modal, setModal] = React.useState(null);
  const [unlocked, setUnlocked] = React.useState([]);
  const handleUnlock = id => {
    setUnlocked(u => [...u, id]);
    setModal(null);
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#0a0806',
      minHeight: '100vh'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      paddingTop: '10rem',
      paddingBottom: '5rem',
      background: '#1a1410',
      borderBottom: '1px solid rgba(139,58,26,0.2)',
      position: 'relative',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      right: -4,
      top: '50%',
      transform: 'translateY(-50%)',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 800,
      fontSize: '16rem',
      lineHeight: 1,
      color: 'rgba(139,58,26,0.04)',
      pointerEvents: 'none',
      whiteSpace: 'nowrap'
    }
  }, "ARCHIVE"), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1100,
      margin: '0 auto',
      padding: '0 4rem',
      position: 'relative',
      zIndex: 1
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, null, "Cast Iron Charlie \xB7 Documentary Research"), /*#__PURE__*/React.createElement("h1", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 900,
      fontSize: 'clamp(2.5rem,5vw,4.5rem)',
      lineHeight: 1.05,
      color: '#faf6f0',
      marginBottom: '1.5rem'
    }
  }, "The", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "Archive")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.95rem',
      color: '#e8e0d4',
      lineHeight: 1.85,
      fontStyle: 'italic',
      maxWidth: 680
    }
  }, "Primary source materials gathered in support of the Cast Iron Charlie documentary. Organized by source and access level."))), /*#__PURE__*/React.createElement("div", {
    style: {
      background: '#0a0806',
      padding: '5rem 0'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1100,
      margin: '0 auto',
      padding: '0 4rem'
    }
  }, /*#__PURE__*/React.createElement(SectionLabel, {
    style: {
      marginBottom: '2.5rem'
    }
  }, "Collections"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: '1.5rem'
    }
  }, COLLECTIONS.map(col => /*#__PURE__*/React.createElement("div", {
    key: col.id,
    style: {
      background: 'rgba(26,20,16,0.6)',
      border: '1px solid rgba(154,144,136,0.15)',
      transition: 'border-color 0.3s, background 0.3s'
    },
    onMouseEnter: e => {
      e.currentTarget.style.borderColor = 'rgba(196,80,26,0.4)';
      e.currentTarget.style.background = 'rgba(26,20,16,0.9)';
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = 'rgba(154,144,136,0.15)';
      e.currentTarget.style.background = 'rgba(26,20,16,0.6)';
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '1.5rem 1.5rem 0'
    }
  }, /*#__PURE__*/React.createElement(StatusBadge, {
    status: col.status
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '1.25rem 1.5rem 2rem'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.65rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: '#C4501A',
      marginBottom: '0.5rem'
    }
  }, col.institution), /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 700,
      fontSize: '1.3rem',
      color: '#faf6f0',
      lineHeight: 1.2,
      marginBottom: '0.75rem'
    }
  }, col.title), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.85rem',
      lineHeight: 1.7,
      color: '#9a9088',
      marginBottom: '1.5rem'
    }
  }, col.desc), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: '1.5rem',
      marginBottom: '1.5rem'
    }
  }, col.stats.map(s => /*#__PURE__*/React.createElement("div", {
    key: s.l
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '1.4rem',
      color: s.accent ? '#C4501A' : '#faf6f0',
      lineHeight: 1
    }
  }, s.n), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.58rem',
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#9a9088'
    }
  }, s.l)))), col.status === 'live' ? /*#__PURE__*/React.createElement("button", {
    onClick: () => unlocked.includes(col.id) ? null : setModal(col.id),
    style: {
      width: '100%',
      background: unlocked.includes(col.id) ? 'rgba(90,158,111,0.15)' : '#C4501A',
      color: unlocked.includes(col.id) ? '#5a9e6f' : '#0a0806',
      border: unlocked.includes(col.id) ? '1px solid rgba(90,158,111,0.3)' : 'none',
      padding: '0.75rem 1.5rem',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '0.75rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      cursor: 'pointer',
      transition: 'all 0.2s'
    }
  }, unlocked.includes(col.id) ? '✓ Unlocked — Scroll to View' : 'Access Collection →') : /*#__PURE__*/React.createElement("button", {
    disabled: true,
    style: {
      width: '100%',
      background: 'rgba(154,144,136,0.15)',
      color: '#9a9088',
      border: 'none',
      padding: '0.75rem 1.5rem',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '0.75rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      cursor: 'default'
    }
  }, "Coming Soon"))))))), unlocked.includes('mfm') && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      height: 1,
      background: 'linear-gradient(to right, transparent, rgba(139,58,26,0.4), transparent)'
    }
  }), /*#__PURE__*/React.createElement(MFMCollection, null)), modal && /*#__PURE__*/React.createElement(PasswordModal, {
    collection: modal,
    onSuccess: handleUnlock,
    onClose: () => setModal(null)
  }), /*#__PURE__*/React.createElement(GradientRule, null), /*#__PURE__*/React.createElement("footer", {
    style: {
      background: '#1a1410',
      borderTop: '1px solid rgba(154,144,136,0.1)',
      padding: '3rem 4rem',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 700,
      fontStyle: 'italic',
      fontSize: '1.1rem',
      color: '#B8922A'
    }
  }, "Cast Iron Charlie"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: '#9a9088',
      textAlign: 'center'
    }
  }, "Research Archive \xB7 Cast Iron Productions LLC"), /*#__PURE__*/React.createElement("button", {
    onClick: () => onNavigate && onNavigate('main'),
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#9a9088',
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      padding: 0
    },
    onMouseEnter: e => e.target.style.color = '#faf6f0',
    onMouseLeave: e => e.target.style.color = '#9a9088'
  }, "\u2190 Main Site")));
}
Object.assign(window, {
  ArchivePage
});
Object.assign(__ds_scope, { ArchivePage });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/ArchivePage.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/ContentSections.jsx
try { (() => {
// ContentSections.jsx — All main page sections for Cast Iron Charlie
// Hook, Story Acts, Willys, WhyNow, Filmmakers, Timeline, Press, Contact, Footer

/* ── shared helpers ─────────────────────────── */
const bodyText = {
  fontFamily: "'Libre Baskerville', serif",
  fontSize: '1rem',
  lineHeight: 1.9,
  color: '#e8e0d4',
  marginBottom: '1.25rem'
};
const h2Style = {
  fontFamily: "'Playfair Display', serif",
  fontWeight: 900,
  fontSize: 'clamp(2rem,4vw,3.5rem)',
  lineHeight: 1.1,
  color: '#faf6f0',
  marginBottom: '1.5rem'
};
const sectionBase = bg => ({
  background: bg,
  position: 'relative'
});

/* ── Hook section ──────────────────────────── */
function HookSection() {
  return /*#__PURE__*/React.createElement("section", {
    id: "hook",
    style: {
      ...sectionBase('#1a1410'),
      borderTop: '1px solid rgba(139,58,26,0.2)'
    }
  }, /*#__PURE__*/React.createElement(SectionInner, null, /*#__PURE__*/React.createElement(SectionLabel, null, "The Untold Story"), /*#__PURE__*/React.createElement("h2", {
    style: {
      ...h2Style,
      marginBottom: '3rem'
    }
  }, "The man who built modern America", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "has been forgotten.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: '4rem',
      alignItems: 'start'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("p", {
    style: bodyText
  }, "Charles Emil Sorensen arrived in America as a blacksmith's son from outside Copenhagen. He rose to become Henry Ford's most trusted lieutenant \u2014 the man who turned the moving assembly line from idea into industrial reality."), /*#__PURE__*/React.createElement("p", {
    style: bodyText
  }, "When World War II came, it was Sorensen who designed Willow Run \u2014 the largest factory ever built, producing a B-24 Liberator bomber every 63 minutes at peak output. He gave America the Jeep. He built the Arsenal of Democracy."), /*#__PURE__*/React.createElement("p", {
    style: {
      ...bodyText,
      marginBottom: 0
    }
  }, "He spent four decades at Ford. He was fired by telegram. America forgot him entirely.")), /*#__PURE__*/React.createElement(PullQuote, {
    quote: "\"He was the greatest production man that ever lived.\" \u2014 Henry Ford",
    cite: "\u2014 as recorded by Charles Sorensen, 1956"
  }))));
}

/* ── Story Acts ────────────────────────────── */
const acts = [{
  n: '01',
  label: 'Act One',
  title: 'The Immigrant',
  body: "From a blacksmith's shop outside Copenhagen to the Ford foundry floor. Sorensen arrives in America with nothing — and earns the trust of the most powerful industrialist in the world."
}, {
  n: '02',
  label: 'Act Two',
  title: 'The Assembly Line',
  body: "The moving assembly line didn't spring fully formed from Henry Ford's mind. It was Sorensen — with his foundry instincts and machinist's eye — who turned the concept into reality at Highland Park."
}, {
  n: '03',
  label: 'Act Three',
  title: 'Arsenal of Democracy',
  body: "One weekend in 1941, Sorensen designed Willow Run on a scratch pad. The result: the largest factory on Earth, producing a B-24 Liberator bomber every 63 minutes. He called it the greatest production achievement in history."
}, {
  n: '04',
  label: 'Act Four',
  title: 'The Forgotten Man',
  body: "In 1944, after forty years, Sorensen was forced out of Ford by telegram. He went to Willys-Overland and gave America the Jeep as a consumer vehicle. Then history moved on — and forgot him entirely."
}];
function StorySection() {
  return /*#__PURE__*/React.createElement("section", {
    id: "story",
    style: sectionBase('#0a0806')
  }, /*#__PURE__*/React.createElement(SectionInner, null, /*#__PURE__*/React.createElement(SectionLabel, null, "The Story"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: 0,
      border: '1px solid rgba(154,144,136,0.15)'
    }
  }, acts.map((act, i) => /*#__PURE__*/React.createElement("div", {
    key: act.n,
    style: {
      padding: '3rem',
      borderRight: i % 2 === 0 ? '1px solid rgba(154,144,136,0.15)' : 'none',
      borderBottom: i < 2 ? '1px solid rgba(154,144,136,0.15)' : 'none',
      position: 'relative',
      transition: 'background 0.4s',
      cursor: 'default'
    },
    onMouseEnter: e => e.currentTarget.style.background = 'rgba(26,20,16,0.8)',
    onMouseLeave: e => e.currentTarget.style.background = 'transparent'
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 800,
      fontSize: '5rem',
      lineHeight: 1,
      color: 'rgba(139,58,26,0.12)',
      position: 'absolute',
      top: '1.5rem',
      right: '2rem'
    }
  }, act.n), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 600,
      fontSize: '0.65rem',
      letterSpacing: '0.4em',
      textTransform: 'uppercase',
      color: '#C4501A',
      marginBottom: '0.75rem'
    }
  }, act.label), /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 700,
      fontSize: '1.6rem',
      color: '#faf6f0',
      marginBottom: '1.25rem',
      lineHeight: 1.2
    }
  }, act.title), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.95rem',
      lineHeight: 1.85,
      color: '#9a9088'
    }
  }, act.body))))));
}

/* ── Willys / Jeep ─────────────────────────── */
function WillysSection() {
  return /*#__PURE__*/React.createElement("section", {
    id: "willys",
    style: {
      ...sectionBase('#2c2420'),
      borderTop: '1px solid rgba(139,58,26,0.2)',
      borderBottom: '1px solid rgba(139,58,26,0.2)'
    }
  }, /*#__PURE__*/React.createElement(SectionInner, null, /*#__PURE__*/React.createElement(SectionLabel, null, "The Jeep"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1.2fr 1fr',
      gap: '6rem',
      alignItems: 'start'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: h2Style
  }, "He gave America", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "the Jeep.")), /*#__PURE__*/React.createElement("p", {
    style: bodyText
  }, "After Henry Ford II forced Sorensen out in 1944, he didn't retire. He went to Willys-Overland and transformed the wartime Jeep into America's first mass-market off-road vehicle."), /*#__PURE__*/React.createElement("p", {
    style: bodyText
  }, "The same production genius that built Willow Run now turned to consumer manufacturing \u2014 and created an entirely new category of American automobile."), /*#__PURE__*/React.createElement("p", {
    style: {
      ...bodyText,
      marginBottom: 0
    }
  }, "The Jeep is now one of the most recognized vehicles in automotive history. Sorensen's name is in none of the brochures.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '1.5rem'
    }
  }, [{
    n: '18,000',
    l: 'B-24 Liberators Built at Willow Run'
  }, {
    n: '63 min',
    l: 'Per Aircraft at Peak Production'
  }, {
    n: '40 yrs',
    l: 'As Henry Ford\'s Top Lieutenant'
  }, {
    n: '1944',
    l: 'Dismissed by Telegram After 40 Years'
  }].map(s => /*#__PURE__*/React.createElement(StatBlock, {
    key: s.l,
    number: s.n,
    label: s.l
  }))))));
}

/* ── Why Now ────────────────────────────────── */
function WhyNowSection() {
  return /*#__PURE__*/React.createElement("section", {
    id: "whynow",
    style: {
      ...sectionBase('#1a1410'),
      borderTop: '1px solid rgba(139,58,26,0.15)',
      borderBottom: '1px solid rgba(139,58,26,0.15)'
    }
  }, /*#__PURE__*/React.createElement(SectionInner, null, /*#__PURE__*/React.createElement(SectionLabel, null, "Why Now"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1.2fr 1fr',
      gap: '6rem',
      alignItems: 'start'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: h2Style
  }, "The moment to tell", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "this story.")), /*#__PURE__*/React.createElement("p", {
    style: bodyText
  }, "The veterans who knew Sorensen personally are gone. The physical plants he built \u2014 Willow Run, River Rouge, the Willys factories \u2014 have been demolished or converted. Primary witnesses have passed."), /*#__PURE__*/React.createElement("p", {
    style: {
      ...bodyText,
      marginBottom: 0
    }
  }, "But the documentary record survives. The archive photographs are newly accessible. The Sorensen memoir, ", /*#__PURE__*/React.createElement("em", null, "My Forty Years with Ford"), ", has been out of print for decades.")), /*#__PURE__*/React.createElement("ul", {
    style: {
      listStyle: 'none',
      display: 'flex',
      flexDirection: 'column',
      gap: '1.25rem',
      padding: 0
    }
  }, ['Last living witnesses to the Willow Run era have passed within the decade', 'Newly accessible photographic archives at Michigan Flight Museum', 'Growing national conversation about industrial legacy and forgotten workers', 'The 80th anniversary of Willow Run\'s peak production year'].map((item, i) => /*#__PURE__*/React.createElement("li", {
    key: i,
    style: {
      display: 'flex',
      gap: '1rem',
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: '#C4501A',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      flexShrink: 0,
      marginTop: '0.1rem'
    }
  }, "\u2014"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.95rem',
      lineHeight: 1.7,
      color: '#e8e0d4'
    }
  }, item)))))));
}

/* ── Timeline ───────────────────────────────── */
const timelineItems = [{
  year: '1881',
  title: 'Born in Odense, Denmark',
  body: 'Son of a blacksmith. Trained as a patternmaker and foundry worker from youth.'
}, {
  year: '1905',
  title: 'Arrives in America',
  body: 'Emigrates to Detroit. Finds work at the Ford Motor Company foundry — and never leaves.'
}, {
  year: '1913',
  title: 'The Moving Assembly Line',
  body: 'Sorensen implements the continuous moving assembly line at Highland Park. Ford production transforms overnight.'
}, {
  year: '1941',
  title: 'Designs Willow Run',
  body: 'On a single weekend, Sorensen sketches the Willow Run bomber plant. Construction begins immediately.'
}, {
  year: '1944',
  title: 'Peak — Then Dismissed',
  body: 'Willow Run reaches a B-24 per hour. Weeks later, Sorensen is forced out of Ford by telegram after 40 years.'
}, {
  year: '1944',
  title: 'To Willys-Overland',
  body: 'Sorensen joins Willys-Overland and transforms the military Jeep into the first consumer off-road vehicle.'
}, {
  year: '1956',
  title: 'My Forty Years with Ford',
  body: 'Publishes his memoir. It goes largely unnoticed. He dies in 1968.'
}];
function TimelineSection() {
  return /*#__PURE__*/React.createElement("section", {
    id: "timeline",
    style: {
      ...sectionBase('#0a0806'),
      borderTop: '1px solid rgba(139,58,26,0.15)'
    }
  }, /*#__PURE__*/React.createElement(SectionInner, null, /*#__PURE__*/React.createElement(SectionLabel, null, "C.E. Sorensen \u2014 Life & Work"), /*#__PURE__*/React.createElement("h2", {
    style: {
      ...h2Style,
      marginBottom: '1rem'
    }
  }, "A Life in", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "Industry")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '1rem',
      color: '#9a9088',
      maxWidth: 600,
      lineHeight: 1.7,
      marginBottom: '4rem'
    }
  }, "Key moments in the life of Charles Emil Sorensen, 1881\u20131968."), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      paddingLeft: '2rem'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: 0,
      top: 0,
      bottom: 0,
      width: 1,
      background: 'linear-gradient(to bottom, transparent, rgba(139,58,26,0.5) 5%, rgba(139,58,26,0.5) 95%, transparent)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: '0 5rem'
    }
  }, timelineItems.map((item, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      position: 'relative',
      paddingLeft: '3rem',
      paddingBottom: '3.5rem'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      left: -5,
      top: '0.35rem',
      width: 11,
      height: 11,
      background: '#C4501A',
      borderRadius: '50%',
      border: '2px solid #0a0806'
    }
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 800,
      fontSize: '0.75rem',
      letterSpacing: '0.3em',
      color: '#C4501A',
      textTransform: 'uppercase',
      marginBottom: '0.4rem'
    }
  }, item.year), /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 700,
      fontSize: '1.15rem',
      color: '#faf6f0',
      marginBottom: '0.5rem',
      lineHeight: 1.3
    }
  }, item.title), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.9rem',
      lineHeight: 1.8,
      color: '#9a9088',
      maxWidth: 400
    }
  }, item.body)))))));
}

/* ── Press / Media Assets ───────────────────── */
const pressItems = [{
  icon: '▤',
  title: 'Press Kit',
  body: 'One-page synopsis, director\'s statement, production stills, and key credits. Available in PDF.'
}, {
  icon: '◫',
  title: 'Photo Gallery',
  body: 'High-resolution production stills and historical archival images cleared for editorial use.'
}, {
  icon: '▷',
  title: 'Trailer / Sizzle Reel',
  body: 'Available to qualified press, festival programmers, and distribution partners on request.'
}, {
  icon: '◉',
  title: 'Interview Requests',
  body: 'The filmmakers are available for print, broadcast, and podcast interviews. Contact below.'
}, {
  icon: '▦',
  title: 'Festival Submissions',
  body: 'Currently in post-production. Festival submission timeline available on request.'
}, {
  icon: '▩',
  title: 'Distribution Inquiries',
  body: 'Seeking distribution partners for theatrical, streaming, and broadcast. Contact via form below.'
}];
function PressSection() {
  return /*#__PURE__*/React.createElement("section", {
    id: "press",
    style: {
      ...sectionBase('#2c2420'),
      borderTop: '1px solid rgba(139,58,26,0.2)',
      borderBottom: '1px solid rgba(139,58,26,0.2)'
    }
  }, /*#__PURE__*/React.createElement(SectionInner, null, /*#__PURE__*/React.createElement(SectionLabel, null, "Press & Media"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: '4rem'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: h2Style
  }, "Press &", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "Media Assets")), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '1rem',
      color: '#9a9088',
      maxWidth: 600,
      lineHeight: 1.7
    }
  }, "Materials available for press, festival programmers, and qualified distribution partners.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(3,1fr)',
      gap: '1.5rem',
      marginBottom: '3rem'
    }
  }, pressItems.map(item => /*#__PURE__*/React.createElement("div", {
    key: item.title,
    style: {
      background: 'rgba(10,8,6,0.5)',
      border: '1px solid rgba(154,144,136,0.12)',
      padding: '2rem',
      transition: 'border-color 0.3s',
      cursor: 'default'
    },
    onMouseEnter: e => e.currentTarget.style.borderColor = 'rgba(196,80,26,0.5)',
    onMouseLeave: e => e.currentTarget.style.borderColor = 'rgba(154,144,136,0.12)'
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: '1.4rem',
      marginBottom: '1.25rem',
      opacity: 0.7,
      fontFamily: 'monospace',
      color: '#9a9088'
    }
  }, item.icon), /*#__PURE__*/React.createElement("h4", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '0.85rem',
      letterSpacing: '0.15em',
      textTransform: 'uppercase',
      color: '#faf6f0',
      marginBottom: '0.5rem'
    }
  }, item.title), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.85rem',
      lineHeight: 1.65,
      color: '#9a9088',
      marginBottom: '1.5rem'
    }
  }, item.body), /*#__PURE__*/React.createElement("a", {
    href: "#contact",
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 600,
      fontSize: '0.7rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: '#C4501A',
      textDecoration: 'none',
      borderBottom: '1px solid rgba(196,80,26,0.3)',
      paddingBottom: '0.15rem'
    }
  }, "Request \u2192"))))));
}

/* ── Contact ────────────────────────────────── */
function ContactSection() {
  const [submitted, setSubmitted] = React.useState(false);
  const [error, setError] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [form, setForm] = React.useState({
    name: '',
    email: '',
    org: '',
    type: 'Press / Media',
    message: '',
    honeypot: ''
  });
  const set = k => e => setForm(f => ({
    ...f,
    [k]: e.target.value
  }));
  const handleSubmit = async e => {
    e.preventDefault();
    setError('');
    setLoading(true);

    // Honeypot check: if honeypot field has data, silently fail
    if (form.honeypot.trim().length > 0) {
      setLoading(false);
      setSubmitted(true);
      return;
    }
    try {
      const response = await fetch('/api/contact', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: form.name,
          email: form.email,
          org: form.org,
          type: form.type,
          message: form.message
        })
      });
      if (response.ok) {
        setSubmitted(true);
        setForm({
          name: '',
          email: '',
          org: '',
          type: 'Press / Media',
          message: '',
          honeypot: ''
        });
      } else {
        const data = await response.json();
        setError(data.error || 'Failed to send message. Please try again.');
      }
    } catch (err) {
      setError('Network error. Please check your connection and try again.');
    } finally {
      setLoading(false);
    }
  };
  const inputStyle = {
    background: 'rgba(26,20,16,0.8)',
    border: '1px solid rgba(154,144,136,0.2)',
    color: '#faf6f0',
    padding: '0.9rem 1rem',
    fontFamily: "'Libre Baskerville', serif",
    fontSize: '0.9rem',
    outline: 'none',
    width: '100%',
    transition: 'border-color 0.3s',
    WebkitAppearance: 'none',
    boxSizing: 'border-box'
  };
  const labelStyle = {
    fontFamily: "'Barlow Condensed', sans-serif",
    fontSize: '0.7rem',
    letterSpacing: '0.3em',
    textTransform: 'uppercase',
    color: '#9a9088',
    display: 'block',
    marginBottom: '0.5rem'
  };
  return /*#__PURE__*/React.createElement("section", {
    id: "contact",
    style: {
      ...sectionBase('#0a0806'),
      borderTop: '1px solid rgba(139,58,26,0.2)'
    }
  }, /*#__PURE__*/React.createElement(SectionInner, null, /*#__PURE__*/React.createElement(SectionLabel, null, "Get in Touch"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1.4fr',
      gap: '6rem',
      alignItems: 'start'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h2", {
    style: {
      ...h2Style,
      fontSize: 'clamp(2.5rem,4vw,4rem)',
      lineHeight: 1.05
    }
  }, "Contact", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "the Team")), /*#__PURE__*/React.createElement("p", {
    style: {
      ...bodyText
    }
  }, "Press inquiries, screening requests, distribution conversations, and archive access requests. We respond to all qualified inquiries."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '1rem',
      marginTop: '3rem',
      paddingTop: '2rem',
      borderTop: '1px solid rgba(154,144,136,0.15)'
    }
  }, [{
    label: 'Email',
    value: 'info@castironcharlie.com'
  }, {
    label: 'Twitter / X',
    value: '@CastFeSorensen'
  }, {
    label: 'Production Company',
    value: 'Cast Iron Productions LLC'
  }, {
    label: 'Location',
    value: 'Tampa, FL'
  }].map(m => /*#__PURE__*/React.createElement("div", {
    key: m.label
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.65rem',
      letterSpacing: '0.35em',
      textTransform: 'uppercase',
      color: '#C4501A',
      marginBottom: '0.2rem'
    }
  }, m.label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.9rem',
      color: '#e8e0d4'
    }
  }, m.value))))), submitted ? /*#__PURE__*/React.createElement("div", {
    style: {
      textAlign: 'center',
      padding: '3rem',
      border: '1px solid rgba(139,58,26,0.3)',
      background: 'rgba(139,58,26,0.06)'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 700,
      fontSize: '1.5rem',
      color: '#faf6f0',
      marginBottom: '1rem'
    }
  }, "Message Received"), /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.95rem',
      color: '#9a9088',
      lineHeight: 1.7
    }
  }, "We'll be in touch shortly. Thank you for your interest in Cast Iron Charlie.")) : /*#__PURE__*/React.createElement("form", {
    onSubmit: handleSubmit,
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '1.25rem'
    }
  }, /*#__PURE__*/React.createElement("input", {
    type: "text",
    name: "honeypot",
    value: form.honeypot,
    onChange: set('honeypot'),
    style: {
      display: 'none'
    },
    tabIndex: -1,
    autoComplete: "off"
  }), error && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '1rem',
      background: 'rgba(196,80,26,0.12)',
      border: '1px solid rgba(196,80,26,0.4)',
      color: '#C4501A',
      fontFamily: "'Libre Baskerville', serif",
      fontSize: '0.9rem',
      lineHeight: 1.6
    }
  }, error), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: '1fr 1fr',
      gap: '1.25rem'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: labelStyle
  }, "Name"), /*#__PURE__*/React.createElement("input", {
    style: inputStyle,
    value: form.name,
    onChange: set('name'),
    required: true,
    onFocus: e => e.target.style.borderColor = '#C4501A',
    onBlur: e => e.target.style.borderColor = 'rgba(154,144,136,0.2)'
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: labelStyle
  }, "Email"), /*#__PURE__*/React.createElement("input", {
    style: inputStyle,
    type: "email",
    value: form.email,
    onChange: set('email'),
    required: true,
    onFocus: e => e.target.style.borderColor = '#C4501A',
    onBlur: e => e.target.style.borderColor = 'rgba(154,144,136,0.2)'
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: labelStyle
  }, "Organization"), /*#__PURE__*/React.createElement("input", {
    style: inputStyle,
    value: form.org,
    onChange: set('org'),
    onFocus: e => e.target.style.borderColor = '#C4501A',
    onBlur: e => e.target.style.borderColor = 'rgba(154,144,136,0.2)'
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: labelStyle
  }, "Inquiry Type"), /*#__PURE__*/React.createElement("select", {
    style: {
      ...inputStyle,
      color: '#e8e0d4',
      cursor: 'pointer'
    },
    value: form.type,
    onChange: set('type')
  }, ['Press / Media', 'Screening Request', 'Distribution', 'Archive Access', 'General'].map(o => /*#__PURE__*/React.createElement("option", {
    key: o,
    style: {
      background: '#1a1410'
    }
  }, o)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("label", {
    style: labelStyle
  }, "Message"), /*#__PURE__*/React.createElement("textarea", {
    style: {
      ...inputStyle,
      resize: 'vertical',
      minHeight: 120
    },
    value: form.message,
    onChange: set('message'),
    onFocus: e => e.target.style.borderColor = '#C4501A',
    onBlur: e => e.target.style.borderColor = 'rgba(154,144,136,0.2)'
  })), /*#__PURE__*/React.createElement("button", {
    type: "submit",
    disabled: loading,
    style: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: '1rem',
      background: loading ? 'rgba(196,80,26,0.4)' : '#C4501A',
      color: '#0a0806',
      border: 'none',
      padding: '1.1rem 2.5rem',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '0.85rem',
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      cursor: loading ? 'not-allowed' : 'pointer',
      alignSelf: 'flex-start',
      transition: 'background 0.3s',
      opacity: loading ? 0.6 : 1
    },
    onMouseEnter: e => {
      if (!loading) e.currentTarget.style.background = '#8B3A1A';
    },
    onMouseLeave: e => {
      if (!loading) e.currentTarget.style.background = '#C4501A';
    }
  }, loading ? 'Sending...' : 'Send Message', " ", /*#__PURE__*/React.createElement("span", null, "\u2192"))))));
}

/* ── Footer ─────────────────────────────────── */
function Footer({
  onNavigate
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(GradientRule, null), /*#__PURE__*/React.createElement("footer", {
    style: {
      background: '#1a1410',
      borderTop: '1px solid rgba(154,144,136,0.1)',
      padding: '3rem 4rem',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 700,
      fontStyle: 'italic',
      fontSize: '1.1rem',
      color: '#B8922A'
    }
  }, "Cast Iron Charlie"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: '#9a9088'
    }
  }, "\xA9 2026 Cast Iron Productions LLC \xB7 Tampa, FL"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: '2rem'
    }
  }, [{
    label: 'Archive',
    action: () => onNavigate && onNavigate('archive')
  }, {
    label: 'Contact',
    action: null
  }, {
    label: '@CastFeSorensen',
    action: null
  }].map(l => /*#__PURE__*/React.createElement("button", {
    key: l.label,
    onClick: l.action,
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#9a9088',
      textDecoration: 'none',
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      transition: 'color 0.3s',
      padding: 0
    },
    onMouseEnter: e => e.target.style.color = '#faf6f0',
    onMouseLeave: e => e.target.style.color = '#9a9088'
  }, l.label)))));
}
Object.assign(window, {
  HookSection,
  StorySection,
  WillysSection,
  WhyNowSection,
  TimelineSection,
  PressSection,
  ContactSection,
  Footer
});

// Barrel export for design system consumption
const ContentSections = {
  HookSection,
  StorySection,
  WillysSection,
  WhyNowSection,
  TimelineSection,
  PressSection,
  ContactSection,
  Footer
};
Object.assign(__ds_scope, { HookSection, StorySection, WillysSection, WhyNowSection, TimelineSection, PressSection, ContactSection, Footer, ContentSections });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/ContentSections.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/Hero.jsx
try { (() => {
// Hero.jsx — Cast Iron Charlie hero section

function Hero({
  onCTAClick
}) {
  const [visible, setVisible] = React.useState(false);
  React.useEffect(() => {
    setTimeout(() => setVisible(true), 50);
  }, []);
  const fadeUp = delay => ({
    opacity: visible ? 1 : 0,
    transform: visible ? 'translateY(0)' : 'translateY(30px)',
    transition: `opacity 1s ease ${delay}s, transform 1s ease ${delay}s`
  });
  return /*#__PURE__*/React.createElement("section", {
    id: "hero",
    style: {
      position: 'relative',
      height: '100vh',
      minHeight: 700,
      display: 'flex',
      alignItems: 'flex-end',
      overflow: 'hidden'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'linear-gradient(135deg, #2c2420 0%, #1a1410 40%, #0a0806 100%)',
      zIndex: 1
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      backgroundImage: `radial-gradient(ellipse at 70% 30%, rgba(44,36,32,0.8) 0%, rgba(10,8,6,0.95) 70%)`,
      zIndex: 1
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'linear-gradient(to top, rgba(10,8,6,1) 0%, rgba(10,8,6,0.4) 40%, rgba(10,8,6,0.2) 100%)',
      zIndex: 2
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      background: 'linear-gradient(to right, rgba(10,8,6,0.6) 0%, transparent 60%)',
      zIndex: 2
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 3,
      padding: '0 4rem 7rem',
      maxWidth: 900
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      ...fadeUp(0.3),
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 600,
      fontSize: '0.75rem',
      letterSpacing: '0.4em',
      textTransform: 'uppercase',
      color: '#C4501A',
      marginBottom: '1.5rem'
    }
  }, "Feature Documentary"), /*#__PURE__*/React.createElement("h1", {
    style: {
      ...fadeUp(0.6),
      fontFamily: "'Playfair Display', serif",
      fontWeight: 900,
      fontSize: 'clamp(4rem, 10vw, 9rem)',
      lineHeight: 0.9,
      color: '#faf6f0',
      marginBottom: '2rem'
    }
  }, "Cast Iron", /*#__PURE__*/React.createElement("br", null), /*#__PURE__*/React.createElement("em", {
    style: {
      fontStyle: 'italic',
      color: '#B8922A'
    }
  }, "Charlie")), /*#__PURE__*/React.createElement("p", {
    style: {
      ...fadeUp(0.9),
      fontFamily: "'Libre Baskerville', serif",
      fontStyle: 'italic',
      fontSize: 'clamp(1rem, 2vw, 1.3rem)',
      color: '#e8e0d4',
      maxWidth: 560,
      lineHeight: 1.7,
      borderLeft: '2px solid #C4501A',
      paddingLeft: '1.5rem',
      marginBottom: '3rem'
    }
  }, "He built the moving assembly line, designed Willow Run, and gave America the Jeep. Denmark sent him. America forgot him."), /*#__PURE__*/React.createElement("a", {
    href: "#hook",
    onClick: onCTAClick,
    style: {
      ...fadeUp(1.2),
      display: 'inline-block',
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '0.85rem',
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      color: '#0a0806',
      background: '#C4501A',
      padding: '1rem 2.5rem',
      textDecoration: 'none',
      transition: 'background 0.3s, transform 0.2s'
    },
    onMouseEnter: e => {
      e.target.style.background = '#8B3A1A';
      e.target.style.transform = 'translateY(-2px)';
    },
    onMouseLeave: e => {
      e.target.style.background = '#C4501A';
      e.target.style.transform = 'translateY(0)';
    }
  }, "Learn the Story \u2192")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: '2.5rem',
      right: '4rem',
      zIndex: 3,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: '0.5rem',
      ...fadeUp(1.5)
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.65rem',
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      color: '#9a9088',
      writingMode: 'vertical-rl'
    }
  }, "Scroll"), /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      height: 60,
      background: 'linear-gradient(to bottom, #9a9088, transparent)'
    }
  })));
}
Object.assign(window, {
  Hero
});
Object.assign(__ds_scope, { Hero });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/Hero.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/Nav.jsx
try { (() => {
// Nav.jsx — Cast Iron Charlie navigation component
// Transparent at top, solid on scroll; mobile hamburger drawer

function Nav({
  currentPage = 'main',
  onNavigate
}) {
  const [scrolled, setScrolled] = React.useState(false);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll, {
      passive: true
    });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  const navLinks = currentPage === 'archive' ? null : [{
    label: 'The Story',
    href: '#hook'
  }, {
    label: 'Willys',
    href: '#willys'
  }, {
    label: 'Why Now',
    href: '#whynow'
  }, {
    label: 'Timeline',
    href: '#timeline'
  }, {
    label: 'Press',
    href: '#press'
  }, {
    label: 'Contact',
    href: '#contact'
  }];
  const linkStyle = {
    fontFamily: "'Barlow Condensed', sans-serif",
    fontWeight: 400,
    fontSize: '0.8rem',
    letterSpacing: '0.2em',
    textTransform: 'uppercase',
    color: '#9a9088',
    textDecoration: 'none',
    transition: 'color 0.3s',
    cursor: 'pointer',
    background: 'none',
    border: 'none',
    padding: 0
  };
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'fixed',
      inset: 0,
      background: 'rgba(10,8,6,0.98)',
      zIndex: 99,
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      gap: '2.5rem',
      opacity: drawerOpen ? 1 : 0,
      pointerEvents: drawerOpen ? 'all' : 'none',
      transition: 'opacity 0.3s'
    }
  }, (navLinks || []).map(l => /*#__PURE__*/React.createElement("a", {
    key: l.label,
    href: l.href,
    onClick: () => setDrawerOpen(false),
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '1.6rem',
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      color: '#e8e0d4',
      textDecoration: 'none'
    }
  }, l.label)), currentPage !== 'archive' && /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => {
      e.preventDefault();
      onNavigate && onNavigate('archive');
      setDrawerOpen(false);
    },
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 700,
      fontSize: '1.6rem',
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      color: '#C4501A',
      textDecoration: 'none'
    }
  }, "Archive")), /*#__PURE__*/React.createElement("nav", {
    style: {
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 100,
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '1.5rem 4rem',
      background: scrolled ? 'rgba(10,8,6,0.97)' : 'linear-gradient(to bottom, rgba(10,8,6,0.95), transparent)',
      transition: 'background 0.3s'
    }
  }, /*#__PURE__*/React.createElement("div", {
    onClick: () => onNavigate && onNavigate('main'),
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 800,
      fontSize: '1rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: '#B8922A',
      cursor: 'pointer'
    }
  }, "Cast Iron Charlie"), currentPage === 'archive' ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: '2rem'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      fontWeight: 600,
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: '#C4501A',
      border: '1px solid rgba(196,80,26,0.4)',
      padding: '0.3rem 0.8rem'
    }
  }, "Research Archive"), /*#__PURE__*/React.createElement("button", {
    onClick: () => onNavigate && onNavigate('main'),
    style: {
      ...linkStyle
    }
  }, "\u2190 Main Site")) : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("ul", {
    style: {
      display: 'flex',
      gap: '2.5rem',
      listStyle: 'none'
    }
  }, navLinks.map(l => /*#__PURE__*/React.createElement("li", {
    key: l.label
  }, /*#__PURE__*/React.createElement("a", {
    href: l.href,
    style: linkStyle,
    onMouseEnter: e => e.target.style.color = '#faf6f0',
    onMouseLeave: e => e.target.style.color = '#9a9088'
  }, l.label))), /*#__PURE__*/React.createElement("li", null, /*#__PURE__*/React.createElement("button", {
    onClick: () => onNavigate && onNavigate('archive'),
    style: {
      ...linkStyle,
      color: '#C4501A'
    }
  }, "Archive"))), /*#__PURE__*/React.createElement("button", {
    onClick: () => setDrawerOpen(o => !o),
    style: {
      display: 'none',
      flexDirection: 'column',
      gap: 5,
      background: 'none',
      border: 'none',
      cursor: 'pointer',
      padding: 4
    },
    "aria-label": "Menu"
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: 24,
      height: 1.5,
      background: '#9a9088',
      display: 'block'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      width: 24,
      height: 1.5,
      background: '#9a9088',
      display: 'block'
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      width: 24,
      height: 1.5,
      background: '#9a9088',
      display: 'block'
    }
  })))));
}
Object.assign(window, {
  Nav
});
Object.assign(__ds_scope, { Nav });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/Nav.jsx", error: String((e && e.message) || e) }); }

// ui_kits/website/SectionComponents.jsx
try { (() => {
// SectionComponents.jsx — Cast Iron Charlie Design System
// Shared low-level components: SectionLabel, PullQuote, StatBlock, GradientRule, Tag, StatusBadge

function SectionLabel({
  children
}) {
  return /*#__PURE__*/React.createElement("p", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 600,
      fontSize: '0.7rem',
      letterSpacing: '0.4em',
      textTransform: 'uppercase',
      color: '#C4501A',
      marginBottom: '3rem',
      display: 'flex',
      alignItems: 'center',
      gap: '1rem'
    }
  }, children, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      maxWidth: 60,
      height: 1,
      background: '#C4501A',
      display: 'inline-block'
    }
  }));
}
function GradientRule() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width: '100%',
      height: 1,
      background: 'linear-gradient(to right, transparent, rgba(139,58,26,0.4), transparent)'
    }
  });
}
function PullQuote({
  quote,
  cite
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      borderLeft: '3px solid #C4501A',
      padding: '2rem 2rem 2rem 2.5rem',
      background: 'rgba(139,58,26,0.06)'
    }
  }, /*#__PURE__*/React.createElement("blockquote", {
    style: {
      fontFamily: "'Playfair Display', serif",
      fontStyle: 'italic',
      fontSize: '1.3rem',
      lineHeight: 1.6,
      color: '#faf6f0',
      marginBottom: cite ? '1.5rem' : 0
    }
  }, quote), cite && /*#__PURE__*/React.createElement("cite", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.75rem',
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      color: '#9a9088',
      fontStyle: 'normal'
    }
  }, cite));
}
function StatBlock({
  number,
  label
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      borderLeft: '3px solid #C4501A',
      padding: '1.25rem 1.5rem',
      background: 'rgba(139,58,26,0.06)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontWeight: 800,
      fontSize: '2.5rem',
      color: '#faf6f0',
      lineHeight: 1,
      marginBottom: '0.25rem'
    }
  }, number), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.7rem',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: '#9a9088'
    }
  }, label));
}
function Tag({
  children,
  variant = 'high'
}) {
  const styles = {
    high: {
      color: '#C4501A',
      borderColor: 'rgba(196,80,26,0.45)',
      background: 'rgba(196,80,26,0.07)'
    },
    medium: {
      color: '#7a9fbf',
      borderColor: 'rgba(122,159,191,0.4)',
      background: 'rgba(122,159,191,0.07)'
    },
    new: {
      color: '#B8922A',
      borderColor: 'rgba(184,146,42,0.45)',
      background: 'rgba(184,146,42,0.07)'
    },
    date: {
      color: '#9a9088',
      borderColor: 'rgba(154,144,136,0.25)',
      background: 'transparent'
    },
    corrected: {
      color: '#C4501A',
      borderColor: 'rgba(196,80,26,0.35)',
      background: 'transparent'
    }
  };
  const s = styles[variant] || styles.high;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.6rem',
      fontWeight: 600,
      letterSpacing: '0.2em',
      textTransform: 'uppercase',
      padding: '0.2rem 0.6rem',
      border: `1px solid ${s.borderColor}`,
      background: s.background,
      color: s.color,
      display: 'inline-block'
    }
  }, children);
}
function StatusBadge({
  status
}) {
  const config = {
    live: {
      label: '● Live',
      color: '#5a9e6f',
      border: 'rgba(90,158,111,0.4)',
      bg: 'rgba(90,158,111,0.08)'
    },
    progress: {
      label: '● In Progress',
      color: '#B8922A',
      border: 'rgba(184,146,42,0.4)',
      bg: 'rgba(184,146,42,0.06)'
    },
    soon: {
      label: 'Coming Soon',
      color: '#9a9088',
      border: 'rgba(154,144,136,0.25)',
      bg: 'transparent'
    }
  };
  const c = config[status] || config.soon;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "'Barlow Condensed', sans-serif",
      fontSize: '0.6rem',
      fontWeight: 600,
      letterSpacing: '0.3em',
      textTransform: 'uppercase',
      padding: '0.4rem 1rem',
      display: 'inline-block',
      color: c.color,
      border: `1px solid ${c.border}`,
      background: c.bg
    }
  }, c.label);
}
function SectionInner({
  children,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 1100,
      margin: '0 auto',
      padding: '7rem 4rem',
      ...style
    }
  }, children);
}
Object.assign(window, {
  SectionLabel,
  GradientRule,
  PullQuote,
  StatBlock,
  Tag,
  StatusBadge,
  SectionInner
});

// Barrel export for design system consumption
const SectionComponents = {
  SectionLabel,
  GradientRule,
  PullQuote,
  StatBlock,
  Tag,
  StatusBadge,
  SectionInner
};
Object.assign(__ds_scope, { SectionLabel, GradientRule, PullQuote, StatBlock, Tag, StatusBadge, SectionInner, SectionComponents });
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/website/SectionComponents.jsx", error: String((e && e.message) || e) }); }

__ds_ns.ArchivePage = __ds_scope.ArchivePage;

__ds_ns.HookSection = __ds_scope.HookSection;

__ds_ns.StorySection = __ds_scope.StorySection;

__ds_ns.WillysSection = __ds_scope.WillysSection;

__ds_ns.WhyNowSection = __ds_scope.WhyNowSection;

__ds_ns.TimelineSection = __ds_scope.TimelineSection;

__ds_ns.PressSection = __ds_scope.PressSection;

__ds_ns.ContactSection = __ds_scope.ContactSection;

__ds_ns.Footer = __ds_scope.Footer;

__ds_ns.ContentSections = __ds_scope.ContentSections;

__ds_ns.Hero = __ds_scope.Hero;

__ds_ns.Nav = __ds_scope.Nav;

__ds_ns.SectionLabel = __ds_scope.SectionLabel;

__ds_ns.GradientRule = __ds_scope.GradientRule;

__ds_ns.PullQuote = __ds_scope.PullQuote;

__ds_ns.StatBlock = __ds_scope.StatBlock;

__ds_ns.Tag = __ds_scope.Tag;

__ds_ns.StatusBadge = __ds_scope.StatusBadge;

__ds_ns.SectionInner = __ds_scope.SectionInner;

__ds_ns.SectionComponents = __ds_scope.SectionComponents;

})();
