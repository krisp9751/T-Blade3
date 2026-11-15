 /*
 ************************************************************************
 *                                                                      *
 * udpTblade -- udp file to generate a turbomachinery blade             *
 *                                                                      *
 *            Written by John Dannenhoffer @ Syracuse University        *
 *            Patterned after code written by Bob Haimes  @ MIT         *
 *                                                                      *
 ************************************************************************
 */

/*
 * Copyright (C) 2011/2020  John F. Dannenhoffer, III (Syracuse University)
 *
 * This library is free software; you can redistribute it and/or
 *    modify it under the terms of the GNU Lesser General Public
 *    License as published by the Free Software Foundation; either
 *    version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 *    but WITHOUT ANY WARRANTY; without even the implied warranty of
 *    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 *    Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 *    License along with this library; if not, write to the Free Software
 *    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
 *     MA  02110-1301  USA
 */

#define NUMUDPARGS 40

/* private data (per UDP instance) used by udpSensitivity; see tbData_T */
#define FREEUDPDATA(A)       freePrivateData(A)
#define COPYUDPDATA(SRC,TGT) copyPrivateData(SRC,TGT)
static int freePrivateData(void *data);
static int copyPrivateData(/*@null@*/void *src, void **tgt);

#include "udpUtilities.h"
#include "egads_dot.h"

#ifdef  DEBUG
   #define DPRINT0(A)         printf(A)
   #define DPRINT1(A,B)       printf(A,B)
   #define DPRINT2(A,B,C)     printf(A,B,C)
   #define DPRINT3(A,B,C,D)   printf(A,B,C,D)
   #define DPRINT4(A,B,C,D,E) printf(A,B,C,D,E)
#else
   #define DPRINT0(A)
   #define DPRINT1(A,B)
   #define DPRINT2(A,B,C)
   #define DPRINT3(A,B,C,D)
   #define DPRINT4(A,B,C,D,E)
#endif

/* shorthands for accessing argument values and velocities */
#define NCP(                IUDP)   ((int    *) (udps[IUDP].arg[ 0].val))[0]
#define SWITCH(		        IUDP)   ((int    *) (udps[IUDP].arg[ 1].val))[0]
#define FILENAME(           IUDP)   ((char   *) (udps[IUDP].arg[ 2].val))
#define AUXNAME(            IUDP)   ((char   *) (udps[IUDP].arg[ 3].val))
#define ARG_2(              IUDP)   ((char   *) (udps[IUDP].arg[ 4].val))
#define VLIMITS(            IUDP,I) ((double *) (udps[IUDP].arg[ 5].val))[I]
#define VLIMITS_SIZE(       IUDP)                udps[IUDP].arg[ 5].size
#define CUR1(               IUDP,I) ((double *) (udps[IUDP].arg[ 6].val))[I]
#define CUR2(               IUDP,I) ((double *) (udps[IUDP].arg[ 7].val))[I]
#define CUR3(               IUDP,I) ((double *) (udps[IUDP].arg[ 8].val))[I]
#define CUR4(               IUDP,I) ((double *) (udps[IUDP].arg[ 9].val))[I]
#define CUR5(               IUDP,I) ((double *) (udps[IUDP].arg[10].val))[I]
#define CUR6(               IUDP,I) ((double *) (udps[IUDP].arg[11].val))[I]
#define CUR7(               IUDP,I) ((double *) (udps[IUDP].arg[12].val))[I]
#define U2(                 IUDP,I) ((double *) (udps[IUDP].arg[13].val))[I]
#define U3(                 IUDP,I) ((double *) (udps[IUDP].arg[14].val))[I]
#define U4(                 IUDP,I) ((double *) (udps[IUDP].arg[15].val))[I]
#define U5(                 IUDP,I) ((double *) (udps[IUDP].arg[16].val))[I]
#define U6(                 IUDP,I) ((double *) (udps[IUDP].arg[17].val))[I]
#define SPAN_DEL_M_CTRL(    IUDP,I) ((double *) (udps[IUDP].arg[18].val))[I]
#define SPAN_DEL_THETA_CTRL(IUDP,I) ((double *) (udps[IUDP].arg[19].val))[I]
#define SPAN_IN_BETA_CTRL(  IUDP,I) ((double *) (udps[IUDP].arg[20].val))[I]
#define SPAN_OUT_BETA_CTRL( IUDP,I) ((double *) (udps[IUDP].arg[21].val))[I]
#define SPAN_CHORD_CTRL(    IUDP,I) ((double *) (udps[IUDP].arg[22].val))[I]
#define SPAN_THK_C_CTRL(    IUDP,I) ((double *) (udps[IUDP].arg[23].val))[I]
#define SPAN_DEL_M(         IUDP,I) ((double *) (udps[IUDP].arg[24].val))[I]
#define SPAN_DEL_THETA(     IUDP,I) ((double *) (udps[IUDP].arg[25].val))[I]
#define SPAN_IN_BETA(       IUDP,I) ((double *) (udps[IUDP].arg[26].val))[I]
#define SPAN_OUT_BETA(      IUDP,I) ((double *) (udps[IUDP].arg[27].val))[I]
#define SPAN_CHORD(         IUDP,I) ((double *) (udps[IUDP].arg[28].val))[I]
#define SPAN_THK_C(         IUDP,I) ((double *) (udps[IUDP].arg[29].val))[I]
#define SPAN_U_MAX(         IUDP,I) ((double *) (udps[IUDP].arg[30].val))[I]
#define SPAN_CURV_CTRL(     IUDP,I) ((double *) (udps[IUDP].arg[31].val))[I]
#define SPAN_THK_CTRL(      IUDP,I) ((double *) (udps[IUDP].arg[32].val))[I]
#define OFFSETS(            IUDP,I) ((double *) (udps[IUDP].arg[33].val))[I]
#define HUB_INF_OFFSET(     IUDP,I) ((double *) (udps[IUDP].arg[34].val))[I]
#define TIP_INF_OFFSET(     IUDP,I) ((double *) (udps[IUDP].arg[35].val))[I]
#define NACA_LE_RADIUS(     IUDP,I) ((double *) (udps[IUDP].arg[36].val))[I]
#define NACA_U_MAX(         IUDP,I) ((double *) (udps[IUDP].arg[37].val))[I]
#define NACA_T_MAX(         IUDP,I) ((double *) (udps[IUDP].arg[38].val))[I]
#define NACA_T_TE(          IUDP,I) ((double *) (udps[IUDP].arg[39].val))[I]


/* data about possible arguments */
static char*  argNames[NUMUDPARGS] = {"ncp",                "switch",               "filename",         "auxname",              
                                      "arg_2",              "vlimits",              "cur1",             "cur2",             
                                      "cur3",               "cur4",                 "cur5",             "cur6",             
                                      "cur7",               "u2",                   "u3",               "u4",                   
                                      "u5",                 "u6",                   "span_del_m_ctrl",  "span_del_theta_ctrl",  
                                      "span_in_beta_ctrl",  "span_out_beta_ctrl",   "span_chord_ctrl",  "span_thk_c_ctrl",      
                                      "span_del_m",         "span_del_theta",       "span_in_beta",     "span_out_beta",        
                                      "span_chord",         "span_thk_c",           "span_u_max",       "span_curv_ctrl",       
                                      "span_thk_ctrl",      "offsets",              "hub_inf_offset",   "tip_inf_offset",       
                                      "naca_le_radius",     "naca_u_max",           "naca_t_max",       "naca_t_te",    };
static int    argTypes[NUMUDPARGS] = {ATTRINT    , ATTRINT    , ATTRSTRING , ATTRSTRING,
                                      ATTRSTRING , ATTRREAL   , ATTRREAL   , ATTRREAL,
                                      ATTRREAL   , ATTRREAL   , ATTRREAL   , ATTRREAL,
                                      ATTRREAL   , ATTRREAL   , ATTRREAL   , ATTRREAL,
                                      ATTRREAL   , ATTRREAL   , ATTRREALSEN, ATTRREALSEN,
                                      ATTRREAL   , ATTRREAL   , ATTRREAL   , ATTRREAL,
                                      ATTRREALSEN, ATTRREALSEN, ATTRREAL   , ATTRREAL,
                                      ATTRREAL   , ATTRREAL   , ATTRREAL   , ATTRREAL,
                                      ATTRREAL   , ATTRREAL   , ATTRREAL   , ATTRREAL,
                                      ATTRREALSEN, ATTRREALSEN, ATTRREALSEN, ATTRREALSEN, };
static int    argIdefs[NUMUDPARGS] = {33,       0,          0,          0,
                                      0,        0,          0,          0,
                                      0,        0,          0,          0,
                                      0,        0,          0,          0,
                                      0,        0,          0,          0,        
                                      0,        0,          0,          0,      
                                      0,        0,          0,          0,
                                      0,        0,          0,          0,
                                      0,        0,          0,          0,
                                      0,        0,          0,          0,  };
static double argDdefs[NUMUDPARGS] = {33.,      0.,         0.,         0.,
                                      0.,       0.,         0.,         0.,
                                      0.,       0.,         0.,         0.,
                                      0.,       0.,         0.,         0.,
                                      0.,       0.,         0.,         0.,       
                                      0.,       0.,         0.,         0.,     
                                      0.,       0.,         0.,         0.,
                                      0.,       0.,         0.,         0.,
                                      0.,       0.,         0.,         0.,       
                                      0.,       0.,         0.,         0., };

/* get utility routines: udpErrorStr, udpInitialize, udpReset, udpSet,
                         udpGet, udpVel, udpClean, udpMesh */
#include "udpUtilities.c"

/* ESP >= 1.24 passes the UDP storage (NumUdp, udps) into udpExecute instead of
   keeping it in globals.  The override_*_ callbacks are called from Fortran with
   fixed signatures, so udpExecute stashes the storage here before calling
   T-Blade3.  NOT thread-safe: do not use with multi-threaded ocsmAdjoint. */
static int   *tb_NumUdp = NULL;
static udp_T *tb_udps   = NULL;
#define TB_UDP_LOCALS  int *NumUdp = tb_NumUdp; udp_T *udps = tb_udps;

/* ---------------------------------------------------------------------
   Analytic sensitivities

   T-Blade3 computes d(x,y,z)/d(control point) for every section point
   (bladestack.f90) and keeps them in memory (file_operations.f90,
   store_xyz_ders).  udpExecute copies the ones for the arguments below
   into the instance's private data.  The blade surface is an EGADS cubic
   fit through the section points, so EG_approximate_dot gives its exact
   sensitivity for any combination of argument dots.  udpSensitivity puts
   those dots on the BSPLINE surface(s) of the Body's blade Faces (private
   copies would be deleted by OpenCSM's sweep of unattached egos) and
   evaluates them at the requested Face/Edge/Node points.
   --------------------------------------------------------------------- */

#define TB_FITTOL   1.0e-8      /* EG_approximate convergence (absolute, model units) */
#define TB_NSENS    8
#ifndef TB_PCTOL
#define TB_PCTOL    1.0e-3      /* EG_otherCurve tolerance for the hub/tip P-curves */
#endif
#ifndef TB_NCPREV
#define TB_NCPREV   6           /* control points of the fallback hub/tip r(x) fit */
#endif

/* UDP argument  <->  T-Blade3 derivative group / parameter (as in xyz_ders_<group>_<k>_<cp>.dat) */
static const int tbSensArg[  TB_NSENS] = {24, 25, 18, 19, 36, 37, 38, 39};
static const int tbSensGroup[TB_NSENS] = { 1,  2,  1,  2,  7,  7,  7,  7};
static const int tbSensK[    TB_NSENS] = { 2,  2,  1,  1,  1,  2,  3,  4};
/*  24 span_del_m          (sweep  value,    group 1, k=2)
    25 span_del_theta      (lean   value,    group 2, k=2)
    18 span_del_m_ctrl     (sweep  span loc, group 1, k=1)
    19 span_del_theta_ctrl (lean   span loc, group 2, k=1)
    36..39 naca_le_radius, naca_u_max, naca_t_max, naca_t_te (group 7, k=1..4) */

typedef struct {
    int     nsec;                 /* number of sections (v direction) */
    int     npnt;                 /* points per section (u direction) */
    double  *xyz;                 /* 3*npnt*nsec section points, u fastest */
    int     nder[TB_NSENS];       /* control points with derivatives (0 = none) */
    double  *der[TB_NSENS];       /* nder*3*npnt*nsec: d(xyz)/d(arg[i]) */
    double  *lastdot;             /* argument dots used for the current surface dots */
    int     nlastdot;
} tbData_T;

/* Fortran (bind(C)) accessors in file_operations.f90 */
extern int tb_get_xyz_ders_size(int iparam, int dims[4]);
extern int tb_get_xyz_ders(     int iparam, int k, int l, double buf[]);

static int tbFetchDerivatives(tbData_T *tb, udp_T *udp);
static int tbStreamlineCap(ego context, const char *which, const char *casename,
                           ego eiso, int npnt, ego *esurface);
static int tbEdgeVel(ego ebody, ego eedge, double t, double vel[]);
static int tbNodeVel(ego ebody, ego enode, double vel[]);
#include <sys/stat.h>
#include <stdio.h>
#include <assert.h>

#ifdef WIN32
   #define SLASH '\\'
#else
   #include <unistd.h>
   #include <libgen.h>
   #define SLASH '/'
#endif

#ifdef GRAFIC
   #include "grafic.h"
   #define DEBUG
#endif

/***********************************************************************/
/*                                                                     */
/* declarations                                                        */
/*                                                                     */
/***********************************************************************/

#define           HUGEQ           99999999.0
#define           PIo2            1.5707963267948965579989817
#define           EPS06           1.0e-06
#define           EPS12           1.0e-12
#define           MIN(A,B)        (((A) < (B)) ? (A) : (B))
#define           MAX(A,B)        (((A) < (B)) ? (B) : (A))
#define           SQR(A)          ((A) * (A))

#ifdef WIN32
   extern void   BGB3D_SUB (char fname[], char sname[], char arg2[], char arg3[], char arg4[],
                            size_t len_fname, size_t len_sname, size_t len_arg2, size_t len_arg3, size_t len_arg4);

   void   OVERRIDE_CUR1 (               int *nspn, double cur1[                 ]);
   void   OVERRIDE_CUR2 (               int *nspn, double cur2[                 ]);
   void   OVERRIDE_CUR3 (               int *nspn, double cur3[                 ]);
   void   OVERRIDE_CUR4 (               int *nspn, double cur4[                 ]);
   void   OVERRIDE_CUR5 (               int *nspn, double cur5[                 ]);
   void   OVERRIDE_CUR6 (               int *nspn, double cur6[                 ]);
   void   OVERRIDE_CUR7 (               int *nspn, double cur7[                 ]);
   void   OVERRIDE_U2 (                 int *nspn, double u2[                   ]);
   void   OVERRIDE_U3 (                 int *nspn, double u3[                   ]);
   void   OVERRIDE_U4 (                 int *nspn, double u4[                   ]);
   void   OVERRIDE_U5 (                 int *nspn, double u5[                   ]);
   void   OVERRIDE_U6 (                 int *nspn, double u6[                   ]);
   void   OVERRIDE_SPAN_DEL_M_CTRL (    int *nspn, double span_del_m_ctrl[      ]);
   void   OVERRIDE_SPAN_DEL_THETA_CTRL (int *nspn, double span_del_theta_ctrl[  ]);
   void   OVERRIDE_SPAN_IN_BETA_CTRL (  int *nspn, double span_in_beta_ctrl[    ]);
   void   OVERRIDE_SPAN_OUT_BETA_CTRL ( int *nspn, double span_out_beta_ctrl[   ]);
   void   OVERRIDE_SPAN_CHORD_CTRL (    int *nspn, double span_chord_ctrl[      ]);
   void   OVERRIDE_SPAN_THK_C_CTRL (    int *nspn, double span_thk_c_ctrl[      ]);
   void   OVERRIDE_SPAN_DEL_M (         int *nspn, double span_del_m[           ]);
   void   OVERRIDE_SPAN_DEL_THETA (     int *nspn, double span_del_theta[       ]);
   void   OVERRIDE_SPAN_IN_BETA (       int *nspn, double span_in_beta[         ]);
   void   OVERRIDE_SPAN_OUT_BETA (      int *nspn, double span_out_beta[        ]);
   void   OVERRIDE_SPAN_CHORD (         int *nspn, double span_chord[           ]);
   void   OVERRIDE_SPAN_THK_C (         int *nspn, double span_thk_c[           ]);
   void   OVERRIDE_SPAN_U_MAX (         int *nspn, double span_u_max[           ]);
   void   OVERRIDE_SPAN_CURV_CTRL (     int *nspn, double span_curv_ctrl[       ]);
   void   OVERRIDE_SPAN_THK_CTRL (      int *nspn, double span_thk_ctrl[        ]);
   void   OVERRIDE_OFFSETS (                       double offsets[              ]);
   void   OVERRIDE_HUB_INF_OFFSET (                double hub_inf_offset[       ]);
   void   OVERRIDE_TIP_INF_OFFSET (                double tip_inf_offset[       ]);
   void   OVERRIDE_NACA_LE_RADIUS (     int *nspn, double naca_le_radius[       ]);
   void   OVERRIDE_NACA_U_MAX (         int *nspn, double naca_u_max[           ]);
   void   OVERRIDE_NACA_T_MAX (         int *nspn, double naca_t_max[           ]);
   void   OVERRIDE_NACA_T_TE (          int *nspn, double naca_t_te[            ]);
#else
   extern void   bgb3d_sub_(char fname[], char sname[], char arg2[], char arg3[],   char arg4[],
                            size_t len_fname, size_t len_sname, size_t len_arg2, size_t len_arg3, size_t len_arg4);

   void   override_cur1_(               int *nspn, double cur1[                 ]);
   void   override_cur2_(               int *nspn, double cur2[                 ]);
   void   override_cur3_(               int *nspn, double cur3[                 ]);
   void   override_cur4_(               int *nspn, double cur4[                 ]);
   void   override_cur5_(               int *nspn, double cur5[                 ]);
   void   override_cur6_(               int *nspn, double cur6[                 ]);
   void   override_cur7_(               int *nspn, double cur7[                 ]);
   void   override_u2_(                 int *nspn, double u2[                   ]);
   void   override_u3_(                 int *nspn, double u3[                   ]);
   void   override_u4_(                 int *nspn, double u4[                   ]);
   void   override_u5_(                 int *nspn, double u5[                   ]);
   void   override_u6_(                 int *nspn, double u6[                   ]);
   void   override_span_del_m_ctrl_(    int *nspn, double span_del_m_ctrl[      ]);
   void   override_span_del_theta_ctrl_(int *nspn, double span_del_theta_ctrl[  ]);
   void   override_span_in_beta_ctrl_(  int *nspn, double span_in_beta_ctrl[    ]);
   void   override_span_out_beta_ctrl_( int *nspn, double span_out_beta_ctrl[   ]);
   void   override_span_chord_ctrl_(    int *nspn, double span_chord_ctrl[      ]);
   void   override_span_thk_c_ctrl_(    int *nspn, double span_thk_c_ctrl[      ]);
   void   override_span_del_m_(         int *nspn, double span_del_m[           ]);
   void   override_span_del_theta_(     int *nspn, double span_del_theta[       ]);
   void   override_span_in_beta_(       int *nspn, double span_in_beta[         ]);
   void   override_span_out_beta_(      int *nspn, double span_out_beta[        ]);
   void   override_span_chord_(         int *nspn, double span_chord[           ]);
   void   override_span_thk_c_(         int *nspn, double span_thk_c[           ]);
   void   override_span_u_max_(         int *nspn, double span_u_max[           ]);
   void   override_span_curv_ctrl_(     int *nspn, double span_curv_ctrl[       ]);
   void   override_span_thk_ctrl_(      int *nspn, double span_thk_ctrl[        ]);
   void   override_offsets_(                       double offsets[              ]);
   void   override_hub_inf_offset_(                double hub_inf_offset[       ]);
   void   override_tip_inf_offset_(                double tip_inf_offset[       ]);
   void   override_naca_le_radius_(     int *nspn, double naca_le_radius[       ]);
   void   override_naca_u_max_(         int *nspn, double naca_u_max[           ]);
   void   override_naca_t_max_(         int *nspn, double naca_t_max[           ]);
   void   override_naca_t_te_(          int *nspn, double naca_t_te[            ]);
#endif

static int    EG_fitBspline(ego context,
                            int npnt, int bitflag, double xyz[],
                            int ncp, ego *ecurve, double *rms);
static int    fit1dCloud(int m, int ordered, double XYZcloud[],
                         int n, double cp[], double *normf);
static int    eval1dBspline(double T, int n, double cp[], double XYZ[],
                            /*@null@*/double dXYZdT[], /*@null@*/double dXYZdP[]);
static int    cubicBsplineBases(int ncp, double t, double N[], double dN[]);
static int    solveSparse(double SAv[], int SAi[], double b[], double x[],
                          int itol, double *errmax, int *iter);
static double L2norm(double f[], int n);

#ifdef GRAFIC
static int    plotCurve(int npnt, double xyz[], ego ecurve);
#endif

#ifdef WIN32
// Returns filename portion of the given path
// Returns empty string if path is directory
const char *basename(const char *path)
{
  const char *filename = strrchr(path, '\\');
  if (filename == NULL)
    filename = path;
  else
    filename++;
  return filename;
}
#endif


/*
 ************************************************************************
 *                                                                      *
 *   udpExecute - execute the primitive                                 *
 *                                                                      *
 ************************************************************************
 */

int
udpExecute(ego  context,                /* (in)  EGADS context */
           ego  *ebody,                 /* (out) Body pointer */
           int  *nMesh,                 /* (out) number of associated meshes */
           char *string[])              /* (out) error message */
{
    udp_T   *udps = *Udps;      /* per-model UDP storage (ESP >= 1.24) */
    int     status = EGADS_SUCCESS;

#define NPNT 1000
    int     ichar, nsec, isec, npnt, ipnt, jpnt, nn, periodic, senses[4];
    int     oclass, mtype, nbody, nface, *senses2, npnt0=0, sizes[2];
    double  vlimits[2], xyz[3*NPNT], rms, xyzNode[18], *xr0=NULL, *xyzAll=NULL;
    double  trange[3], tt, data[18], data2[18], swap, srange[4], umid, vlo, vhi;
    tbData_T *tb=NULL;
    ego     eiso=NULL;
    double  toler = 1e-4;
    char    filename[257], auxname[257], *auxptr, nextline[257], casename[257];
    FILE    *fp, *fpSrc=NULL, *fpTgt=NULL;
    ego     enodes[5], eedges[4], eloop;
    ego     ecurve, epcurve, esurface, esurf, eref, efaces[4], emodel, *ebodys;

    DPRINT1("udpExecute(context=%llx)\n", (long long)context);
    DPRINT1("ncp(     0) = %d\n", NCP(     0));
    DPRINT1("switch(     0) = %d\n", SWITCH(     0));
    DPRINT1("filename(0) = %s\n", FILENAME(0));
    DPRINT1("auxname( 0) = %s\n", AUXNAME( 0));

    /* default return values */
    *ebody  = NULL;
    *nMesh  = 0;
    *string = NULL;

    /* check arguments */
    if (VLIMITS_SIZE(0) == 2) {
        vlimits[0] = MAX(0, VLIMITS(0,0));
        vlimits[1] = MIN(1, VLIMITS(0,1));
    } else {
        vlimits[0] = 0;
        vlimits[1] = 1;
    }

    if (vlimits[1] <= vlimits[0]) {
        printf(" udpExecute: vlimits[0] = %f should be less than vlimits[1] = %f\n", vlimits[0], vlimits[1]);
        status  = EGADS_RANGERR;
        goto cleanup;
    }
    
    /* make the Tblade3_temp2 temporary directory */
    status = mkdir("Tblade3_temp2", 0777);
    if (status < 0) {
        printf(" udpExecute: could not \"mkdir Tblade3_temp2\".  If it already exists, files may be overwritten.\n");
    }

    /* copy the input files to the Tblade3_temp directory */
    snprintf(filename, 256, "Tblade3_temp2%c%s", SLASH, basename(FILENAME(0)));
    DPRINT1("FILENAME(0)=%s\n", FILENAME(0));
    DPRINT1("fileame    =%s\n", filename   );

    fpSrc = fopen(FILENAME(0), "r");
    fpTgt = fopen(filename,    "w");

    if (fpSrc != NULL && fpTgt != NULL) {
        while (1) {
            ichar = fgetc(fpSrc);
            if (ichar != EOF) {
                fputc(ichar, fpTgt);
            } else {
                break;
            }
        }
    } else {
        printf(" udpExecute: could not copy \"%s\"\n", FILENAME(0));
        status = EGADS_NOTFOUND;
        goto cleanup;
    }

    if (fpSrc != NULL) {
        fclose(fpSrc);
        fpSrc = NULL;
    }
    if (fpTgt != NULL) {
        fclose(fpTgt);
        fpTgt = NULL;
    }

    auxptr = strstr(AUXNAME(0), "spancontrolinputs");
    if (auxptr == NULL) {
        auxptr = strstr(AUXNAME(0), "controlinputs");
        if (auxptr == NULL) {
            printf(" udpExecute: \"%s\" is not a valid auxname\n", AUXNAME(0));
            status = EGADS_NOTFOUND;
            goto cleanup;
        }
    }

    snprintf(auxname, 256, "Tblade3_temp2%c%s", SLASH, auxptr);
    DPRINT1("AUXNAME(0)=%s\n", AUXNAME(0));
    DPRINT1("auxname   =%s\n", auxname   );

    fpSrc = fopen(AUXNAME(0), "r");
    fpTgt = fopen(auxname,    "w");

    if (fpSrc != NULL && fpTgt != NULL) {
        while (1) {
            ichar = fgetc(fpSrc);
            if (ichar != EOF) {
                fputc(ichar, fpTgt);
            } else {
                break;
            }
        }
    } else {
        printf(" udpExecute: could not copy \"%s\"\n", AUXNAME(0));
        status = EGADS_NOTFOUND;
        goto cleanup;
    }

    if (fpSrc != NULL) {
        fclose(fpSrc);
        fpSrc = NULL;
    }
    if (fpTgt != NULL) {
        fclose(fpTgt);
        fpTgt = NULL;
    }

    /* change working directory to Tblade3_temp2 so that all temporary
       files are kept together */
    status = chdir("Tblade3_temp2");
    if (status < 0) {
        printf(" udpExecute: could not change to \"Tblade3_temp2\"\n");
        status = EGADS_EMPTY;
        return status; 
    }

    /* cache copy of arguments for future use */
    status = cacheUdp(NULL);
    tb_NumUdp = NumUdp;
    tb_udps   = udps;
    if (status < 0) {
        printf(" udpExecute: problem caching arguments\n");
        goto cleanup;
    }

    DPRINT2("ncp(     %d) = %d\n", numUdp, NCP(     numUdp));
    DPRINT2("switch(     %d) = %d\n", numUdp, SWITCH(     numUdp));
    DPRINT2("filename(%d) = %s\n", numUdp, FILENAME(numUdp));
    DPRINT2("auxname( %d) = %s\n", numUdp, AUXNAME( numUdp));

    /* open the input file to extract the casename and number of sections */
    snprintf(filename, 256, "%s", basename(FILENAME(numUdp)));

    fp = fopen(filename, "r");
    if (fp == NULL) {
        printf(" udpExecute: could not open \"%s\"\n", filename);
        status = EGADS_NOTFOUND;
        goto cleanup;
    }

    /* read the file line by line */
    (void) fgets(nextline, 257, fp);
    (void) fgets(nextline, 257, fp);
    sscanf(nextline, "%s", casename);

    (void) fgets(nextline, 257, fp);
    (void) fgets(nextline, 257, fp);

    (void) fgets(nextline, 257, fp);
    (void) fgets(nextline, 257, fp);

    (void) fgets(nextline, 257, fp);
    (void) fgets(nextline, 257, fp);

    (void) fgets(nextline, 257, fp);
    (void) fgets(nextline, 257, fp);
    sscanf(nextline, "%d", &nsec);

    fclose(fp);

    /* try running Tblade */
    if (SWITCH(0) != 1) {
#ifdef WIN32
        BGB3D_SUB (filename, AUXNAME(numUdp), ARG_2(numUdp), "", "",
               strlen(filename), strlen(AUXNAME(numUdp)), (int)strlen(ARG_2(numUdp)), strlen(""), strlen(""));
#else
        bgb3d_sub_(filename, AUXNAME(numUdp), ARG_2(numUdp), "", "",
               strlen(filename), strlen(AUXNAME(numUdp)), (int)strlen(ARG_2(numUdp)), strlen(""), strlen(""));
#endif 
    }

    /* read all of the sections into one (npnt x nsec) grid */
    for (isec = 1; isec <= nsec; isec++) {
        snprintf(filename, 256, "sec%d.%s.dat", isec, casename);
        printf("reading: %s\n", filename);

        fp = fopen(filename, "r");
        if (fp == NULL) {
            printf(" udpExecute: could not open \"%s\"\n", filename);
            status = EGADS_NOTFOUND;
            goto cleanup;
        }

        npnt = 0;
        while (1) {
            if (npnt >= NPNT) {
                printf(" udpExecute: more than NPNT=%d points in \"%s\"\n", NPNT, filename);
                fclose(fp);
                status = EGADS_RANGERR;
                goto cleanup;
            }
            nn = fscanf(fp, "%lf %lf %lf\n", &(xyz[3*npnt]), &(xyz[3*npnt+1]), &(xyz[3*npnt+2]));
            if (nn < 3) break;
            npnt++;
        }
        fclose(fp);
        DPRINT2("section %2d has %d points\n", isec, npnt);

        if (isec == 1) {
            npnt0  = npnt;
            if (npnt0 < 4) {
                printf(" udpExecute: section 1 has only %d points\n", npnt0);
                status = EGADS_RANGERR;
                goto cleanup;
            }
            xyzAll = (double*) malloc(3*npnt0*nsec*sizeof(double));
            if (xyzAll == NULL) {
                status = EGADS_MALLOC;
                goto cleanup;
            }
        } else if (npnt != npnt0) {
            printf(" udpExecute: section %d has %d points but section 1 has %d\n", isec, npnt, npnt0);
            status = EGADS_RANGERR;
            goto cleanup;
        }
        memcpy(&(xyzAll[3*npnt0*(isec-1)]), xyz, 3*npnt0*sizeof(double));
    }
    npnt = npnt0;

    /* create the blade surface: an EGADS cubic fit through all section
       points (u along each section, v across sections), so that
       EG_approximate_dot gives its exact sensitivity */
    sizes[0] = npnt0;
    sizes[1] = nsec;
    status = EG_approximate(context, 0, TB_FITTOL, sizes, xyzAll, &esurf);
    DPRINT1("EG_approximate -> status=%d\n", status);
    if (status != EGADS_SUCCESS) goto cleanup;

    status = EG_getRange(esurf, srange, &periodic);
    if (status != EGADS_SUCCESS) goto cleanup;

    umid = (srange[0] + srange[1]) / 2;
    vlo  = srange[2] + vlimits[0] * (srange[3] - srange[2]);
    vhi  = srange[2] + vlimits[1] * (srange[3] - srange[2]);

    /* break the surface into 2 Faces */
    data[0] = srange[0];
    data[1] = umid;
    data[2] = vlo;
    data[3] = vhi;
    DPRINT4("data(limits)=%f, %f, %f, %f\n", data[0], data[1], data[2], data[3]);

    status = EG_makeFace(esurf, SFORWARD, data, &(efaces[0]));
    DPRINT1("EG_makeFace -> status=%d\n", status);
    if (status != EGADS_SUCCESS) goto cleanup;

    data[0] = umid;
    data[1] = srange[1];

    status = EG_makeFace(esurf, SFORWARD, data, &(efaces[1]));
    DPRINT1("EG_makeFace -> status=%d\n", status);
    if (status != EGADS_SUCCESS) goto cleanup;

    nface = 2;

    /* generate the hub and tip Faces */
    for (isec = 1; isec <= nsec; isec += (nsec-1)) {
        if (isec == 1    && vlimits[0] > 0) continue;
        if (isec == nsec && vlimits[1] < 1) continue;

        DPRINT1("making end-cap to produce Face[%d]\n", nface);

        /* the section curve at constant V on the blade surface */
        if (isec == 1) {
            status = EG_isoCline(esurf, VISO, vlo, &eiso);
        } else {
            status = EG_isoCline(esurf, VISO, vhi, &eiso);
        }
        DPRINT1("EG_isoCline -> status=%d\n", status);
        if (status != EGADS_SUCCESS) goto cleanup;

        status = EG_getRange(eiso, trange, &periodic);
        if (status != EGADS_SUCCESS) goto cleanup;

        /* preferred cap surface: revolve T-Blade3's hub/casing streamline (the
           flow-path surface).  It does not depend on the blade design variables,
           so the caps have zero normal velocity.  Fall back to a fit of the end
           section itself if the section is not on it (e.g. inflated hub/tip) */
        esurface = NULL;
        status = tbStreamlineCap(context, (isec == 1) ? "hub" : "casing", casename,
                                 eiso, npnt, &esurface);
        if (status != EGADS_SUCCESS) {
            esurface = NULL;
        }

        if (esurface == NULL) {
            /* make a fit of r vs. x*/
            xr0 = (double*) malloc(3*npnt*sizeof(double));
            if (xr0 == NULL) {
                status = EGADS_MALLOC;
                goto cleanup;
            }

            status = EG_getRange(eiso, trange, &periodic);
            DPRINT3("EG_getRange -> status=%d, trange=%f, %f\n", status, trange[0], trange[1]);
            if (status != EGADS_SUCCESS) goto cleanup;

            for (ipnt = 0; ipnt < npnt; ipnt++) {
                tt = trange[0] + (double)(ipnt) / (double)(npnt-1) * (trange[1] - trange[0]);

                status = EG_evaluate(eiso, &tt, data2);
                if (status != EGADS_SUCCESS) goto cleanup;

                xr0[3*ipnt  ] = data2[0];
                xr0[3*ipnt+1] = sqrt(data2[1]*data2[1] + data2[2]*data2[2]);
                xr0[3*ipnt+2] = 0;
            }

            /* order the points based upon x (using SLOW bubble sort) */
            for (ipnt = 0; ipnt < npnt-1; ipnt++) {
                for (jpnt = ipnt+1; jpnt < npnt; jpnt++) {
                    if (xr0[3*ipnt] > xr0[3*jpnt]) {
                        swap = xr0[3*ipnt  ]; xr0[3*ipnt  ] = xr0[3*jpnt  ]; xr0[3*jpnt  ] = swap;
                        swap = xr0[3*ipnt+1]; xr0[3*ipnt+1] = xr0[3*jpnt+1]; xr0[3*jpnt+1] = swap;
                        swap = xr0[3*ipnt+2]; xr0[3*ipnt+2] = xr0[3*jpnt+2]; xr0[3*jpnt+2] = swap;
                    }
                }
            }

            /* arbitrarily extend surface beyond xmin and xmax */
            xr0[3] =     xr0[0];
            xr0[4] =     xr0[1];
            xr0[5] =     xr0[2];
            xr0[0] = 2 * xr0[3] - xr0[30];
            xr0[1] = 2 * xr0[4] - xr0[31];
            xr0[2] = 2 * xr0[5] - xr0[32];

            xr0[3*npnt-6] =     xr0[3*npnt-3];
            xr0[3*npnt-5] =     xr0[3*npnt-2];
            xr0[3*npnt-4] =     xr0[3*npnt-1];
            xr0[3*npnt-3] = 2 * xr0[3*npnt-6] - xr0[3*npnt-30];
            xr0[3*npnt-2] = 2 * xr0[3*npnt-5] - xr0[3*npnt-29];
            xr0[3*npnt-1] = 2 * xr0[3*npnt-4] - xr0[3*npnt-28];

            status = EG_fitBspline(context, npnt, 1, xr0, TB_NCPREV, &ecurve, &rms);
            DPRINT2("EG_fitBspline -> status=%d, rms=%f\n", status, rms);
            if (status != EGADS_SUCCESS) goto cleanup;

            free(xr0);
            xr0 = NULL;

#ifdef GRAFIC
            /* plot the fit */
            status = plotCurve(npnt, xr0, ecurve);
            if (status != EGADS_SUCCESS) goto cleanup;
#endif

            /* make a surface of revolution */
            data[0] = data[1] = data[2] = 0;
            data[3] = 1;
            data[4] = data[5] = 0;
            status = EG_makeGeometry(context, SURFACE, REVOLUTION, ecurve,
                                     NULL, data, &esurface);
            DPRINT1("EG_makeGeometry -> status=%d\n", status);
            if (status != EGADS_SUCCESS) goto cleanup;

        }

        /* create the Face, split at the same u as the blade Faces */
        trange[2] =  trange[1];
        trange[1] =  umid;

        status = EG_evaluate(eiso, &(trange[0]), xyzNode);
        DPRINT4("EG_evaluate -> status=%d, xyzNode=%f %f %f\n",
               status, xyzNode[0], xyzNode[1], xyzNode[2]);
        if (status != EGADS_SUCCESS) goto cleanup;

        status = EG_makeTopology(context, NULL, NODE, 0,
                                 xyzNode, 0, NULL, NULL, &(enodes[0]));
        DPRINT1("EG_makeTopology(node0) -> status=%d\n", status);
        if (status != EGADS_SUCCESS) goto cleanup;

        status = EG_evaluate(eiso, &(trange[1]), xyzNode);
        DPRINT4("EG_evaluate -> status=%d, xyzNode=%f %f %f\n",
                status, xyzNode[0], xyzNode[1], xyzNode[2]);
        if (status != EGADS_SUCCESS) goto cleanup;

        status = EG_makeTopology(context, NULL, NODE, 0,
                                 xyzNode, 0, NULL, NULL, &(enodes[1]));
        DPRINT1("EG_makeTopology(node1) -> status=%d\n", status);
        if (status != EGADS_SUCCESS) goto cleanup;

        enodes[2] = enodes[0];

        /* create the two Edges for this section */
        status = EG_makeTopology(context, eiso, EDGE, TWONODE,
                                 trange, 2, &(enodes[0]), NULL, &(eedges[0]));
        DPRINT1("EG_makeTopology(edge0) -> status=%d\n", status);
        if (status != EGADS_SUCCESS) goto cleanup;

        status = EG_makeTopology(context, eiso, EDGE, TWONODE,
                                 &(trange[1]), 2, &(enodes[1]), NULL, &(eedges[1]));
        DPRINT1("EG_makeTopology(edge1) -> status=%d\n", status);
        if (status != EGADS_SUCCESS) goto cleanup;

        /* create the Loop for this section, with one P-curve per Edge (a single
           P-curve for the whole closed section fits poorly near the LE) */
        for (ipnt = 0; ipnt < 2; ipnt++) {
            ego etrim;

            status = EG_makeGeometry(context, CURVE, TRIMMED, eiso, NULL,
                                     &(trange[ipnt]), &etrim);
            DPRINT1("EG_makeGeometry(trimmed) -> status=%d\n", status);
            if (status != EGADS_SUCCESS) goto cleanup;

            status = EG_otherCurve(esurface, etrim, TB_PCTOL, &epcurve);
            DPRINT1("EG_otherCurve -> status=%d\n", status);
            if (status != EGADS_SUCCESS) goto cleanup;

            eedges[2+ipnt] = epcurve;
        }

        senses[0] = SFORWARD;
        senses[1] = SFORWARD;
        status = EG_makeTopology(context, esurface, LOOP, CLOSED,
                                 NULL, 2, eedges, senses, &eloop);
        DPRINT1("EG_makeTopology(loop) -> status=%d\n", status);
        if (status != EGADS_SUCCESS) goto cleanup;

        status = EG_makeTopology(context, esurface, FACE, SFORWARD,
                                 NULL, 1, &eloop, senses, &(efaces[nface]));
        DPRINT1("EG_makeTopology(face) -> status=%d\n", status);
        if (status != EGADS_SUCCESS) goto cleanup;

        nface++;
    }

    /* sew the Faces into a SolidBody */
    status = EG_sewFaces(nface, efaces, toler, 0, &emodel);
    DPRINT1("EG_sewFaces -> status=%d\n", status);
    if (status != EGADS_SUCCESS) goto cleanup;

    status = EG_getTopology(emodel, &eref, &oclass, &mtype,
                            data, &nbody, &ebodys, &senses2);
    DPRINT2("EG_getTopology(model) -> status=%d, nbody=%d\n", status, nbody);
    if (status != EGADS_SUCCESS) goto cleanup;

    /* copy the Body out of the sewn Model so the Model can be freed */
    status = EG_copyObject(ebodys[0], NULL, ebody);
    DPRINT1("EG_copyObject -> status=%d\n", status);
    EG_deleteObject(emodel);
    if (status != EGADS_SUCCESS) goto cleanup;

    /* set the output value(s) */

    /* remember this model (body) */
    udps[numUdp].ebody = *ebody;

    /* private data for udpSensitivity */
    tb = (tbData_T*) calloc(1, sizeof(tbData_T));
    if (tb == NULL) {
        status = EGADS_MALLOC;
        goto cleanup;
    }
    tb->nsec = nsec;
    tb->npnt = npnt0;
    tb->xyz  = xyzAll;
    xyzAll   = NULL;

    /* the derivatives exist only if T-Blade3 actually ran */
    if (SWITCH(numUdp) != 1) {
        status = tbFetchDerivatives(tb, &(udps[numUdp]));
        if (status != EGADS_SUCCESS) goto cleanup;
    }

    if (udps[numUdp].data != NULL) {
        (void) freePrivateData(udps[numUdp].data);
    }
    udps[numUdp].data = tb;
    tb = NULL;

    DPRINT1("udpExecute -> *ebody=%llx\n", (long long)(*ebody));

cleanup:

    /* change working directory back */
    chdir("./..");

    if (xyzAll  != NULL) free(xyzAll);
    if (tb      != NULL) (void) freePrivateData(tb);

    if (xr0 != NULL) free(xr0);

    if (status != EGADS_SUCCESS) {
        *string = udpErrorStr(status);
    }

    return status;
}


/*
 ************************************************************************
 *                                                                      *
 *   udpSensitivity - return sensitivity derivatives for the "real" argument *
 *                                                                      *
 ************************************************************************
 */

int
udpSensitivity(ego    ebody,            /* (in)  Body pointer */
               int    npnt,             /* (in)  number of points */
               int    entType,          /* (in)  OCSM entity type */
               int    entIndex,         /* (in)  OCSM entity index (bias-1) */
               double uvs[],            /* (in)  parametric coordinates for evaluation */
               double vels[])           /* (out) velocities */
{
    int      status = EGADS_SUCCESS;
    int      iudp, judp, isen, iarg, i, j, n, ndot, changed, ipnt, sizes[2];
    int      oclass, mtype, nchild, *senses, *ivec=NULL, nent;
    double   *dgrid=NULL, *dots=NULL, data[18], data_dot[18], *rvec=NULL;
    int      nface, iface, nbsurf, k;
    ego      eref, *echilds, *eents=NULL, *efaces=NULL, esurf, bsurf[4];
    tbData_T *tb;

#ifdef DEBUG
    printf("udpSensitivity(ebody=%llx, npnt=%d, entType=%d, entIndex=%d)\n",
           (long long)ebody, npnt, entType, entIndex);
#endif

    /* check that ebody matches one of the ebodys */
    iudp = 0;
    for (judp = 1; judp <= numUdp; judp++) {
        if (ebody == udps[judp].ebody) {
            iudp = judp;
            break;
        }
    }
    if (iudp <= 0) {
        return EGADS_NOTMODEL;
    }

    tb = (tbData_T *) udps[iudp].data;
    if (tb == NULL || tb->xyz == NULL) {
        return EGADS_NOLOAD;            /* OpenCSM falls back to finite differences */
    }

    /* the distinct BSPLINE surfaces under the blade Faces */
    status = EG_getBodyTopos(ebody, NULL, FACE, &nface, &efaces);
    if (status != EGADS_SUCCESS) goto cleanup;

    nbsurf = 0;
    for (iface = 0; iface < nface; iface++) {
        status = EG_getTopology(efaces[iface], &esurf, &oclass, &mtype,
                                data, &nchild, &echilds, &senses);
        if (status != EGADS_SUCCESS) goto cleanup;
        if (esurf->mtype != BSPLINE) continue;
        for (k = 0; k < nbsurf; k++) {
            if (bsurf[k] == esurf) break;
        }
        if (k == nbsurf && nbsurf < 4) bsurf[nbsurf++] = esurf;
    }
    if (nbsurf == 0) {
        status = EGADS_NOLOAD;
        goto cleanup;
    }

    /* gather the current argument dots (only the ATTRREALSEN arguments have them) */
    ndot = 0;
    for (isen = 0; isen < TB_NSENS; isen++) {
        ndot += udps[iudp].arg[tbSensArg[isen]].size;
    }
    dots = (double *) malloc(ndot*sizeof(double));
    if (dots == NULL) {
        status = EGADS_MALLOC;
        goto cleanup;
    }
    n = 0;
    for (isen = 0; isen < TB_NSENS; isen++) {
        iarg = tbSensArg[isen];
        for (i = 0; i < udps[iudp].arg[iarg].size; i++) {
            dots[n++] = (udps[iudp].arg[iarg].dot != NULL) ? udps[iudp].arg[iarg].dot[i] : 0;
        }
    }

    /* (re)compute the dots on the private surface if the argument dots changed */
    changed = (udps[iudp].ndotchg != 0 || tb->lastdot == NULL || tb->nlastdot != ndot);
    for (k = 0; k < nbsurf; k++) {
        if (EG_hasGeometry_dot(bsurf[k]) != EGADS_SUCCESS) changed = 1;
    }
    for (i = 0; changed == 0 && i < ndot; i++) {
        if (dots[i] != tb->lastdot[i]) changed = 1;
    }

    if (changed) {
        n = 3 * tb->npnt * tb->nsec;
        dgrid = (double *) calloc(n, sizeof(double));
        if (dgrid == NULL) {
            status = EGADS_MALLOC;
            goto cleanup;
        }

        /* d(xyz) = sum over arguments and control points of dot * d(xyz)/d(arg) */
        for (isen = 0; isen < TB_NSENS; isen++) {
            iarg = tbSensArg[isen];
            if (udps[iudp].arg[iarg].dot == NULL || tb->der[isen] == NULL) continue;
            for (i = 0; i < tb->nder[isen] && i < udps[iudp].arg[iarg].size; i++) {
                double d = udps[iudp].arg[iarg].dot[i];
                if (d == 0) continue;
                for (j = 0; j < n; j++) {
                    dgrid[j] += d * tb->der[isen][(long)i*n+j];
                }
            }
        }

        sizes[0] = tb->npnt;
        sizes[1] = tb->nsec;
        for (k = 0; k < nbsurf; k++) {
            status = EG_approximate_dot(bsurf[k], 0, TB_FITTOL, sizes, tb->xyz, dgrid);
            if (status != EGADS_SUCCESS) {
                printf(" udpSensitivity: EG_approximate_dot -> status=%d\n", status);
                goto cleanup;
            }
        }

        free(tb->lastdot);
        tb->lastdot  = dots;
        tb->nlastdot = ndot;
        dots         = NULL;
    }

    /* OpenCSM calls with npnt=0 right after udpExecute */
    if (npnt <= 0) goto cleanup;

    if (entType == OCSM_FACE) {
        status = EG_getBodyTopos(ebody, NULL, FACE, &nent, &eents);
        if (status != EGADS_SUCCESS) goto cleanup;
        if (entIndex < 1 || entIndex > nent) {
            status = EGADS_INDEXERR;
            goto cleanup;
        }

        /* the blade Faces lie on a BSPLINE; the hub/tip caps are surfaces of
           revolution of the (fixed) flow-path contour, so their normal velocity
           is zero */
        status = EG_getTopology(eents[entIndex-1], &esurf, &oclass, &mtype,
                                data, &nchild, &echilds, &senses);
        if (status != EGADS_SUCCESS) goto cleanup;
        status = EG_getGeometry(esurf, &oclass, &mtype, &eref, &ivec, &rvec);
        if (status != EGADS_SUCCESS) goto cleanup;

        for (ipnt = 0; ipnt < npnt; ipnt++) {
            if (mtype != BSPLINE) {
                vels[3*ipnt  ] = 0;
                vels[3*ipnt+1] = 0;
                vels[3*ipnt+2] = 0;
                continue;
            }
            status = EG_evaluate_dot(esurf, &(uvs[2*ipnt]), NULL, data, data_dot);
            if (status != EGADS_SUCCESS) goto cleanup;
            vels[3*ipnt  ] = data_dot[0];
            vels[3*ipnt+1] = data_dot[1];
            vels[3*ipnt+2] = data_dot[2];
        }

    } else if (entType == OCSM_EDGE) {
        status = EG_getBodyTopos(ebody, NULL, EDGE, &nent, &eents);
        if (status != EGADS_SUCCESS) goto cleanup;
        if (entIndex < 1 || entIndex > nent) {
            status = EGADS_INDEXERR;
            goto cleanup;
        }

        /* every Edge bounds a blade Face: use its (u,v) on that Face */
        for (ipnt = 0; ipnt < npnt; ipnt++) {
            status = tbEdgeVel(ebody, eents[entIndex-1], uvs[ipnt], &(vels[3*ipnt]));
            if (status != EGADS_SUCCESS) goto cleanup;
        }

    } else if (entType == OCSM_NODE) {
        status = EG_getBodyTopos(ebody, NULL, NODE, &nent, &eents);
        if (status != EGADS_SUCCESS) goto cleanup;
        if (entIndex < 1 || entIndex > nent) {
            status = EGADS_INDEXERR;
            goto cleanup;
        }

        status = tbNodeVel(ebody, eents[entIndex-1], &(vels[0]));
        if (status != EGADS_SUCCESS) goto cleanup;
        for (ipnt = 1; ipnt < npnt; ipnt++) {
            vels[3*ipnt  ] = vels[0];
            vels[3*ipnt+1] = vels[1];
            vels[3*ipnt+2] = vels[2];
        }

    } else {
        printf(" udpSensitivity: bad entType=%d\n", entType);
        status = EGADS_ATTRERR;
        goto cleanup;
    }

cleanup:
    if (eents  != NULL) EG_free(eents);
    if (efaces != NULL) EG_free(efaces);
    if (ivec   != NULL) EG_free(ivec);
    if (rvec  != NULL) EG_free(rvec);
    if (dgrid != NULL) free(dgrid);
    if (dots  != NULL) free(dots);

    return status;
}


/*
 ************************************************************************
 *                                                                      *
 *   tbEdgeVel - velocity of a point on an Edge of the blade Body       *
 *                                                                      *
 ************************************************************************
 */

static int
tbEdgeVel(ego    ebody,                 /* (in)  Body */
          ego    eedge,                 /* (in)  Edge */
          double t,                     /* (in)  Edge parameter */
          double vel[])                 /* (out) d(xyz)/d(design) */
{
    int    status = EGADS_NOTFOUND;
    int    nface, iface, oclass, mtype, nchild, *senses, stat2;
    double uv[2], data[18], data_dot[18];
    ego    *efaces=NULL, esurf, *echilds;

    stat2 = EG_getBodyTopos(ebody, eedge, FACE, &nface, &efaces);
    if (stat2 != EGADS_SUCCESS) {
        status = stat2;
        goto cleanup;
    }

    /* use the first adjacent blade (BSPLINE) Face */
    for (iface = 0; iface < nface; iface++) {
        stat2 = EG_getTopology(efaces[iface], &esurf, &oclass, &mtype,
                               data, &nchild, &echilds, &senses);
        if (stat2 != EGADS_SUCCESS || esurf->mtype != BSPLINE) continue;

        stat2 = EG_getEdgeUV(efaces[iface], eedge, 0, t, uv);
        if (stat2 != EGADS_SUCCESS) continue;

        status = EG_evaluate_dot(esurf, uv, NULL, data, data_dot);
        if (status != EGADS_SUCCESS) goto cleanup;

        vel[0] = data_dot[0];
        vel[1] = data_dot[1];
        vel[2] = data_dot[2];
        break;
    }

cleanup:
    if (efaces != NULL) EG_free(efaces);
    return status;
}


/*
 ************************************************************************
 *                                                                      *
 *   tbNodeVel - velocity of a Node of the blade Body                   *
 *                                                                      *
 ************************************************************************
 */

static int
tbNodeVel(ego    ebody,                 /* (in)  Body */
          ego    enode,                 /* (in)  Node */
          double vel[])                 /* (out) d(xyz)/d(design) */
{
    int    status = EGADS_NOTFOUND;
    int    nedge, iedge, oclass, mtype, nnode, *senses;
    double trange[4], t;
    ego    *eedges=NULL, eref, *enodes;

    status = EG_getBodyTopos(ebody, enode, EDGE, &nedge, &eedges);
    if (status != EGADS_SUCCESS) goto cleanup;

    status = EGADS_NOTFOUND;
    for (iedge = 0; iedge < nedge; iedge++) {
        if (EG_getTopology(eedges[iedge], &eref, &oclass, &mtype, trange,
                           &nnode, &enodes, &senses) != EGADS_SUCCESS) continue;
        if (mtype == DEGENERATE) continue;
        if (enodes[0] == enode) {
            t = trange[0];
        } else if (nnode > 1 && enodes[1] == enode) {
            t = trange[1];
        } else {
            continue;
        }
        status = tbEdgeVel(ebody, eedges[iedge], t, vel);
        if (status == EGADS_SUCCESS) break;
    }

cleanup:
    if (eedges != NULL) EG_free(eedges);
    return status;
}

/*
 ************************************************************************
 *                                                                      *
 *   tbFetchDerivatives - copy T-Blade3's section derivatives           *
 *                                                                      *
 ************************************************************************
 */

static int
tbFetchDerivatives(tbData_T *tb,        /* (both) private data */
                   udp_T    *udp)       /* (in)   this UDP instance */
{
    int    isen, iarg, l, dims[4], n;

    n = 3 * tb->npnt * tb->nsec;

    for (isen = 0; isen < TB_NSENS; isen++) {
        tb->nder[isen] = 0;
        tb->der[ isen] = NULL;

        iarg = tbSensArg[isen];
        if (tb_get_xyz_ders_size(tbSensGroup[isen], dims) != 0) continue;

        if (dims[0] != tb->nsec || dims[1] != tb->npnt || tbSensK[isen] > dims[2]) {
            printf(" udpTblade: derivative group %d is %dx%dx%d, expected %dx%dx>=%d (no sensitivities for %s)\n",
                   tbSensGroup[isen], dims[0], dims[1], dims[2], tb->nsec, tb->npnt, tbSensK[isen], argNames[iarg]);
            continue;
        }

        /* T-Blade3 only uses the argument (override_*) when its size matches
           the number of control points; otherwise the argument has no effect
           and its sensitivity is zero */
        if (udp->arg[iarg].size != dims[3]) continue;

        tb->der[isen] = (double *) malloc((long)dims[3]*n*sizeof(double));
        if (tb->der[isen] == NULL) return EGADS_MALLOC;

        for (l = 0; l < dims[3]; l++) {
            if (tb_get_xyz_ders(tbSensGroup[isen], tbSensK[isen], l+1, &(tb->der[isen][(long)l*n])) != 0) {
                free(tb->der[isen]);
                tb->der[isen] = NULL;
                break;
            }
        }
        if (tb->der[isen] != NULL) tb->nder[isen] = dims[3];
    }

    return EGADS_SUCCESS;
}



/*
 ************************************************************************
 *                                                                      *
 *   tbStreamlineCap - surface of revolution of the hub/casing          *
 *                     streamline written by T-Blade3                   *
 *                                                                      *
 ************************************************************************
 */

#define TB_CAPTOL   1.0e-3      /* max distance (relative to radius) of the end section from the cap */

static int
tbStreamlineCap(ego        context,     /* (in)  EGADS context */
                const char *which,      /* (in)  "hub" or "casing" */
                const char *casename,   /* (in)  T-Blade3 case name */
                ego        eiso,        /* (in)  end section of the blade surface */
                int        npnt,        /* (in)  number of points to check */
                ego        *esurface)   /* (out) REVOLUTION surface (NULL if not usable) */
{
    int    status = EGADS_SUCCESS;
    int    n, nalloc, sizes[2], ipnt, periodic;
    double *xr=NULL, x, y, z, data[18], uv[2], xyz[3], res[3], trange[2], tt, dist, dmax, rmax;
    char   fname[300];
    FILE   *fp=NULL;
    ego    ecurve=NULL, esurf=NULL;

    *esurface = NULL;

    snprintf(fname, 299, "%s.%s.sldcrv", which, casename);
    fp = fopen(fname, "r");
    if (fp == NULL) {
        status = EGADS_NOTFOUND;
        goto cleanup;
    }

    /* file has x, 0, r (already scaled) */
    n      = 0;
    nalloc = 0;
    while (fscanf(fp, "%lf %lf %lf", &x, &y, &z) == 3) {
        if (n >= nalloc) {
            double *tmp;
            nalloc += 100;
            tmp = (double *) realloc(xr, 3*nalloc*sizeof(double));
            if (tmp == NULL) {
                status = EGADS_MALLOC;
                goto cleanup;
            }
            xr = tmp;
        }
        xr[3*n  ] = x;
        xr[3*n+1] = sqrt(y*y + z*z);
        xr[3*n+2] = 0;
        n++;
    }
    if (n < 4) {
        status = EGADS_NODATA;
        goto cleanup;
    }

    /* cubic curve through the streamline points, revolved about the x axis */
    sizes[0] = n;
    sizes[1] = 0;
    status = EG_approximate(context, 0, TB_FITTOL, sizes, xr, &ecurve);
    if (status != EGADS_SUCCESS) goto cleanup;

    data[0] = data[1] = data[2] = 0;
    data[3] = 1;
    data[4] = data[5] = 0;
    status = EG_makeGeometry(context, SURFACE, REVOLUTION, ecurve, NULL, data, &esurf);
    if (status != EGADS_SUCCESS) goto cleanup;

    /* the end section must lie on it */
    status = EG_getRange(eiso, trange, &periodic);
    if (status != EGADS_SUCCESS) goto cleanup;

    dmax = 0;
    rmax = 0;
    for (ipnt = 0; ipnt < npnt; ipnt++) {
        tt = trange[0] + (double)(ipnt) / (double)(npnt-1) * (trange[1] - trange[0]);
        status = EG_evaluate(eiso, &tt, data);
        if (status != EGADS_SUCCESS) goto cleanup;
        xyz[0] = data[0];
        xyz[1] = data[1];
        xyz[2] = data[2];
        status = EG_invEvaluate(esurf, xyz, uv, res);
        if (status != EGADS_SUCCESS) goto cleanup;
        dist = sqrt(SQR(res[0]-xyz[0]) + SQR(res[1]-xyz[1]) + SQR(res[2]-xyz[2]));
        dmax = MAX(dmax, dist);
        rmax = MAX(rmax, sqrt(SQR(xyz[1]) + SQR(xyz[2])));
    }

    if (dmax > TB_CAPTOL * rmax) {
        printf(" udpTblade: %s section is %g from the %s streamline surface; fitting the section instead\n",
               which, dmax, which);
        status = EGADS_RANGERR;
        goto cleanup;
    }
    DPRINT2("udpTblade: %s cap from streamline, max distance %g\n", which, dmax);

    *esurface = esurf;
    esurf     = NULL;

cleanup:
    if (fp    != NULL) fclose(fp);
    if (xr    != NULL) free(xr);
    if (esurf != NULL) EG_deleteObject(esurf);

    return status;
}

/*
 ************************************************************************
 *                                                                      *
 *   freePrivateData - free the private data of one UDP instance        *
 *                                                                      *
 ************************************************************************
 */

static int
freePrivateData(void *data)
{
    int      isen;
    tbData_T *tb = (tbData_T *) data;

    if (tb == NULL) return EGADS_SUCCESS;

    free(tb->xyz);
    for (isen = 0; isen < TB_NSENS; isen++) free(tb->der[isen]);
    free(tb->lastdot);
    free(tb);

    return EGADS_SUCCESS;
}


/*
 ************************************************************************
 *                                                                      *
 *   copyPrivateData - deep copy of the private data                    *
 *                                                                      *
 ************************************************************************
 */

static int
copyPrivateData(/*@null@*/void *src,
                          void **tgt)
{
    int      isen, n;
    tbData_T *from = (tbData_T *) src, *to;

    *tgt = NULL;
    if (from == NULL) return EGADS_SUCCESS;

    to = (tbData_T *) calloc(1, sizeof(tbData_T));
    if (to == NULL) return EGADS_MALLOC;

    n = 3 * from->npnt * from->nsec;
    to->nsec = from->nsec;
    to->npnt = from->npnt;

    to->xyz = (double *) malloc(n*sizeof(double));
    if (to->xyz == NULL) goto oom;
    memcpy(to->xyz, from->xyz, n*sizeof(double));

    for (isen = 0; isen < TB_NSENS; isen++) {
        if (from->der[isen] == NULL) continue;
        to->der[isen] = (double *) malloc((long)from->nder[isen]*n*sizeof(double));
        if (to->der[isen] == NULL) goto oom;
        memcpy(to->der[isen], from->der[isen], (long)from->nder[isen]*n*sizeof(double));
        to->nder[isen] = from->nder[isen];
    }

    *tgt = to;
    return EGADS_SUCCESS;

oom:
    (void) freePrivateData(to);
    return EGADS_MALLOC;
}


/*
 ************************************************************************
 *                                                                      *
 *   override_cur1 - callback from T-Blade3 to change cur1 array        *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_CUR1 (int *nspn, double cur1[])
#else
void override_cur1_(int *nspn, double cur1[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=6;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding cur1\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            cur1[ispn] = CUR1(numUdp,ispn);
            printf("     cur1(%2d) = %12.5f\n", ispn+1, cur1[ispn]);
        }
    } else {
        printf(" ==> not overriding cur1 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_cur2 - callback from T-Blade3 to change cur2 array        *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_CUR2 (int *nspn, double cur2[])
#else
void override_cur2_(int *nspn, double cur2[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=7;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding cur2\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            cur2[ispn] = CUR2(numUdp,ispn);
            printf("     cur2(%2d) = %12.5f\n", ispn+1, cur2[ispn]);
        }
    } else {
        printf(" ==> not overriding cur2 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_cur3 - callback from T-Blade3 to change cur3 array        *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_CUR3 (int *nspn, double cur3[])
#else
void override_cur3_(int *nspn, double cur3[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=8;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding cur3\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            cur3[ispn] = CUR3(numUdp,ispn);
            printf("     cur3(%2d) = %12.5f\n", ispn+1, cur3[ispn]);
        }
    } else {
        printf(" ==> not overriding cur3 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_cur4 - callback from T-Blade3 to change cur4 array        *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_CUR4 (int *nspn, double cur4[])
#else
void override_cur4_(int *nspn, double cur4[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=9;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding cur4\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            cur4[ispn] = CUR4(numUdp,ispn);
            printf("     cur4(%2d) = %12.5f\n", ispn+1, cur4[ispn]);
        }
    } else {
        printf(" ==> not overriding cur4 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_cur5 - callback from T-Blade3 to change cur5 array        *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_CUR5 (int *nspn, double cur5[])
#else
void override_cur5_(int *nspn, double cur5[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=10;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding cur5\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            cur5[ispn] = CUR5(numUdp,ispn);
            printf("     cur5(%2d) = %12.5f\n", ispn+1, cur5[ispn]);
        }
    } else {
        printf(" ==> not overriding cur5 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_cur6 - callback from T-Blade3 to change cur6 array        *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_CUR6 (int *nspn, double cur6[])
#else
void override_cur6_(int *nspn, double cur6[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=11;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding cur6\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            cur6[ispn] = CUR6(numUdp,ispn);
            printf("     cur6(%2d) = %12.5f\n", ispn+1, cur6[ispn]);
        }
    } else {
        printf(" ==> not overriding cur6 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_cur7 - callback from T-Blade3 to change cur7 array        *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_CUR7 (int *nspn, double cur7[])
#else
void override_cur7_(int *nspn, double cur7[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=12;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding cur7\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            cur7[ispn] = CUR7(numUdp,ispn);
            printf("     cur7(%2d) = %12.5f\n", ispn+1, cur7[ispn]);
        }
    } else {
        printf(" ==> not overriding cur7 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_u2 - callback from T-Blade3 to change u2 array            *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_U2 (int *nspn, double u2[])
#else
void override_u2_(int *nspn, double u2[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=13;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding u2\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            u2[ispn] = U2(numUdp,ispn);
            printf("     u2(%2d) = %12.5f\n", ispn+1, u2[ispn]);
        }
    } else {
        printf(" ==> not overriding u2 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_u3 - callback from T-Blade3 to change u3 array            *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_U3 (int *nspn, double u3[])
#else
void override_u3_(int *nspn, double u3[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=14;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding u3\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            u3[ispn] = U3(numUdp,ispn);
            printf("     u3(%2d) = %12.5f\n", ispn+1, u3[ispn]);
        }
    } else {
        printf(" ==> not overriding u3 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_u4 - callback from T-Blade3 to change u4 array            *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_U4 (int *nspn, double u4[])
#else
void override_u4_(int *nspn, double u4[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=15;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding u4\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            u4[ispn] = U4(numUdp,ispn);
            printf("     u4(%2d) = %12.5f\n", ispn+1, u4[ispn]);
        }
    } else {
        printf(" ==> not overriding u4 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_u5 - callback from T-Blade3 to change u5 array            *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_U5 (int *nspn, double u5[])
#else
void override_u5_(int *nspn, double u5[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=16;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding u5\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            u5[ispn] = U5(numUdp,ispn);
            printf("     u5(%2d) = %12.5f\n", ispn+1, u5[ispn]);
        }
    } else {
        printf(" ==> not overriding u5 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_u6 - callback from T-Blade3 to change u6 array            *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_U6 (int *nspn, double u6[])
#else
void override_u6_(int *nspn, double u6[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=17;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding u6\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            u6[ispn] = U6(numUdp,ispn);
            printf("     u6(%2d) = %12.5f\n", ispn+1, u6[ispn]);
        }
    } else {
        printf(" ==> not overriding u6 (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_del_m_ctrl - callback from T-Blade3 to change        *
 *                              span_del_m_ctrl array                   *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_DEL_M_CTRL (int *nspn, double span_del_m_ctrl[])
#else
void override_span_del_m_ctrl_(int *nspn, double span_del_m_ctrl[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=18;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_del_m_ctrl\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_del_m_ctrl[ispn] = SPAN_DEL_M_CTRL(numUdp,ispn);
            printf("     span_del_m_ctrl(%2d) = %12.5f\n", ispn+1, span_del_m_ctrl[ispn]);
        }
    } else {
        printf(" ==> not overriding span_del_m_ctrl (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_del_theta_ctrl - callback from T-Blade3 to change    *
 *                                  span_del_theta_ctrl array           *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_DEL_THETA_CTRL (int *nspn, double span_del_theta_ctrl[])
#else
void override_span_del_theta_ctrl_(int *nspn, double span_del_theta_ctrl[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=19;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_del_theta_ctrl\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_del_theta_ctrl[ispn] = SPAN_DEL_THETA_CTRL(numUdp,ispn);
            printf("     span_del_theta_ctrl(%2d) = %12.5f\n", ispn+1, span_del_theta_ctrl[ispn]);
        }
    } else {
        printf(" ==> not overriding span_del_theta_ctrl (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_in_beta_ctrl - callback from T-Blade3 to change      *
 *                                span_in_beta_ctrl array               *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_IN_BETA_CTRL (int *nspn, double span_in_beta_ctrl[])
#else
void override_span_in_beta_ctrl_(int *nspn, double span_in_beta_ctrl[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=20;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_in_beta_ctrl\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_in_beta_ctrl[ispn] = SPAN_IN_BETA_CTRL(numUdp,ispn);
            printf("     span_in_beta_ctrl(%2d) = %12.5f\n", ispn+1, span_in_beta_ctrl[ispn]);
        }
    } else {
        printf(" ==> not overriding span_in_beta_ctrl (nspn=%d but size=%d)\n",
                *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_out_beta_ctrl - callback from T-Blade3 to change     *
 *                                 span_out_beta_ctrl array             *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_OUT_BETA_CTRL (int *nspn, double span_out_beta_ctrl[])
#else
void override_span_out_beta_ctrl_(int *nspn, double span_out_beta_ctrl[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=21;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_out_beta_ctrl\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_out_beta_ctrl[ispn] = SPAN_OUT_BETA_CTRL(numUdp,ispn);
            printf("     span_out_beta_ctrl(%2d) = %12.5f\n", ispn+1, span_out_beta_ctrl[ispn]);
        }
    } else {
        printf(" ==> not overriding span_out_beta_ctrl (nspn=%d but size=%d)\n",
                *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_chord_ctrl - callback from T-Blade3 to change        *
 *                              span_chord_ctrl array                   *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_CHORD_CTRL (int *nspn, double span_chord_ctrl[])
#else
void override_span_chord_ctrl_(int *nspn, double span_chord_ctrl[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=22;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_chord_ctrl\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_chord_ctrl[ispn] = SPAN_CHORD_CTRL(numUdp,ispn);
            printf("     span_chord_ctrl(%2d) = %12.5f\n", ispn+1, span_chord_ctrl[ispn]);
        }
    } else {
        printf(" ==> not overriding span_chord_ctrl (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_thk_c_ctrl - callback from T-Blade3 to change        *
 *                              span_thk_c_ctrl array                   *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_THK_C_CTRL (int *nspn, double span_thk_c_ctrl[])
#else
void override_span_thk_c_ctrl_(int *nspn, double span_thk_c_ctrl[])
#endif
{
    TB_UDP_LOCALS
    int   ispn, narg=23;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_thk_c_ctrl\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_thk_c_ctrl[ispn] = SPAN_THK_C_CTRL(numUdp,ispn);
            printf("     span_thk_c_ctrl(%2d) = %12.5f\n", ispn+1, span_thk_c_ctrl[ispn]);
        }
    } else {
        printf(" ==> not overriding span_thk_c_ctrl (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_del_m - callback from T-Blade3 to change             *
 *                         span_del_m array                             *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_DEL_M (int *nspn, double span_del_m[])
#else
void override_span_del_m_(int *nspn, double span_del_m[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=24;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_del_m\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_del_m[ispn] = SPAN_DEL_M(numUdp,ispn);
            printf("     span_del_m(%2d) = %12.5f\n", ispn+1, span_del_m[ispn]);
        }
    } else {
        printf(" ==> not overriding span_del_m (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_del_theta - callback from T-Blade3 to change         *
 *                             span_del_theta array                     *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_DEL_THETA (int *nspn, double span_del_theta[])
#else
void override_span_del_theta_(int *nspn, double span_del_theta[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=25;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_del_theta\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_del_theta[ispn] = SPAN_DEL_THETA(numUdp,ispn);
            printf("     span_del_theta(%2d) = %12.5f\n", ispn+1, span_del_theta[ispn]);
        }
    } else {
        printf(" ==> not overriding span_del_theta (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_in_beta - callback from T-Blade3 to change           *
 *                           span_in_beta array                         *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_IN_BETA (int *nspn, double span_in_beta[])
#else
void override_span_in_beta_(int *nspn, double span_in_beta[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=26;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_in_beta\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_in_beta[ispn] = SPAN_IN_BETA(numUdp,ispn);
            printf("     span_in_beta(%2d) = %12.5f\n", ispn+1, span_in_beta[ispn]);
        }
    } else {
        printf(" ==> not overriding span_in_beta (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_out_beta - callback from T-Blade3 to change          *
 *                            span_out_beta array                       *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_OUT_BETA (int *nspn, double span_out_beta[])
#else
void override_span_out_beta_(int *nspn, double span_out_beta[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=27;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_out_beta\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_out_beta[ispn] = SPAN_OUT_BETA(numUdp,ispn);
            printf("     span_out_beta(%2d) = %12.5f\n", ispn+1, span_out_beta[ispn]);
        }
    } else {
        printf(" ==> not overriding span_out_beta (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_chord - callback from T-Blade3 to change             *
 *                         span_chord array                             *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_CHORD (int *nspn, double span_chord[])
#else
void override_span_chord_(int *nspn, double span_chord[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=28;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_chord\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_chord[ispn] = SPAN_CHORD(numUdp,ispn);
            printf("     span_chord(%2d) = %12.5f\n", ispn+1, span_chord[ispn]);
        }
    } else {
        printf(" ==> not overriding span_chord (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_thk_c - callback from T-Blade3 to change             *
 *                         span_thk_c array                             *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_THK_C (int *nspn, double span_thk_c[])
#else
void override_span_thk_c_(int *nspn, double span_thk_c[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=29;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_thk_c\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_thk_c[ispn] = SPAN_THK_C(numUdp,ispn);
            printf("     span_thk_c(%2d) = %12.5f\n", ispn+1, span_thk_c[ispn]);
        }
    } else {
        printf(" ==> not overriding span_thk_c (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_u_max - callback from T-Blade3 to change             *
 *                         span_u_max array                             *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_U_MAX (int *nspn, double span_u_max[])
#else
void override_span_u_max_(int *nspn, double span_u_max[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=30;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_u_max\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_u_max[ispn] = SPAN_U_MAX(numUdp,ispn);
            printf("     span_u_max(%2d) = %12.5f\n", ispn+1, span_u_max[ispn]);
        }
    } else{
        printf(" ==> not overriding span_u_max (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_curv_ctrl - callback from T-Blade3 to change         *
 *                             span_curv_ctrl array                     *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_CURV_CTRL (int *nspn, double span_curv_ctrl[])
#else
void override_span_curv_ctrl_(int *nspn, double span_curv_ctrl[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=31;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_curv_ctrl\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_curv_ctrl[ispn] = SPAN_CURV_CTRL(numUdp,ispn);
            printf("     span_curv_ctrl(%2d) = %12.5f\n", ispn+1, span_curv_ctrl[ispn]);
        }
    } else {
        printf(" ==> not overriding span_curv_ctrl (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_span_thk_ctrl - callback from T-Blade3 to change          *
 *                            span_thk_ctrl array                       *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_SPAN_THK_CTRL (int *nspn, double span_thk_ctrl[])
#else
void override_span_thk_ctrl_(int *nspn, double span_thk_ctrl[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=32;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding span_thk_ctrl\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            span_thk_ctrl[ispn] = SPAN_THK_CTRL(numUdp,ispn);
            printf("     span_thk_ctrl(%2d) = %12.5f\n", ispn+1, span_thk_ctrl[ispn]);
        }
    } else {
        printf(" ==> not overriding span_thk_ctrl (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_offsets - callback from T-Blade3 to change                *
 *                      offsets array                                   *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_OFFSETS (double offsets[])
#else
void override_offsets_(double offsets[])
#endif
{
    TB_UDP_LOCALS
    int    ioffset, narg=33;

    if (udps[numUdp].arg[narg].size == 2) {
        printf(" ==> overriding offsets\n");
        for (ioffset = 0; ioffset < 2; ioffset++) {
            offsets[ioffset] = OFFSETS(numUdp,ioffset);
            printf("     offsets(%2d) = %12.5f\n", ioffset+1, offsets[ioffset]);
        }
    } else {
        printf(" ==> not overriding offsets (noffset=2 but size=%d)\n",
               udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_hub_inf_offset - callback from T-Blade3 to change         *
 *                             hub_inf_offset                           *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_HUB_INF_OFFSET (double hub_inf_offset[])
#else
void override_hub_inf_offset_(double hub_inf_offset[])
#endif
{
    TB_UDP_LOCALS
    int    narg=34;

    if (udps[numUdp].arg[narg].size == 1) {
        printf(" ==> overriding hub_inf_offset\n");
        hub_inf_offset[0] = HUB_INF_OFFSET(numUdp,0);
        printf("      hub_inf_offset(%2d) = %12.5f\n", 1, hub_inf_offset[0]);
    } else {
        printf(" ==> not overriding hub_inf_offset (noffset=1 but size=%d)\n",
               udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_tip_inf_offset - callback from T-Blade3 to change         *
 *                             tip_inf_offset                           *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_TIP_INF_OFFSET (double tip_inf_offset[])
#else
void override_tip_inf_offset_(double tip_inf_offset[])
#endif
{
    TB_UDP_LOCALS
    int    narg=35;

    if (udps[numUdp].arg[narg].size == 1) {
        printf(" ==> overriding tip_inf_offset\n");
        tip_inf_offset[0] = TIP_INF_OFFSET(numUdp,0);
        printf("      tip_inf_offset(%2d) = %12.5f\n", 1, tip_inf_offset[0]);
    } else {
        printf(" ==> not overriding tip_inf_offset (noffset=1 but size=%d)\n",
               udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_naca_le_radius - callback from T-Blade3 to change         *
 *                             naca_le_radius array                     *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_NACA_LE_RADIUS (int *nspn, double naca_le_radius[])
#else
void override_naca_le_radius_(int *nspn, double naca_le_radius[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=36;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding naca_le_radius\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            naca_le_radius[ispn] = NACA_LE_RADIUS(numUdp,ispn);
            printf("     naca_le_radius(%2d) = %12.5f\n", ispn+1, naca_le_radius[ispn]);
        }
    } else {
        printf(" ==> not overriding naca_le_radius (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_naca_u_max - callback from T-Blade3 to change             *
 *                         naca_u_max array                             *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_NACA_U_MAX (int *nspn, double naca_u_max[])
#else
void override_naca_u_max_(int *nspn, double naca_u_max[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=37;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding naca_u_max\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            naca_u_max[ispn] = NACA_U_MAX(numUdp,ispn);
            printf("     naca_u_max(%2d) = %12.5f\n", ispn+1, naca_u_max[ispn]);
        }
    } else {
        printf(" ==> not overriding naca_u_max (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_naca_t_max - callback from T-Blade3 to change             *
 *                         naca_t_max array                             *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_NACA_T_MAX (int *nspn, double naca_t_max[])
#else
void override_naca_t_max_(int *nspn, double naca_t_max[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=38;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding naca_t_max\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            naca_t_max[ispn] = NACA_T_MAX(numUdp,ispn);
            printf("     naca_t_max(%2d) = %12.5f\n", ispn+1, naca_t_max[ispn]);
        }
    } else {
        printf(" ==> not overriding naca_t_max (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   override_naca_t_te - callback from T-Blade3 to change              *
 *                        naca_t_te array                               *
 *                                                                      *
 ************************************************************************
 */

#ifdef WIN32
void OVERRIDE_NACA_T_TE (int *nspn, double naca_t_te[])
#else
void override_naca_t_te_(int *nspn, double naca_t_te[])
#endif
{
    TB_UDP_LOCALS
    int    ispn, narg=39;

    if (udps[numUdp].arg[narg].size == *nspn) {
        printf(" ==> overriding naca_t_te\n");
        for (ispn = 0; ispn < *nspn; ispn++) {
            naca_t_te[ispn] = NACA_T_TE(numUdp,ispn);
            printf("     naca_t_te(%2d) = %12.5f\n", ispn+1, naca_t_te[ispn]);
        }
    } else {
        printf(" ==> not overriding naca_t_te (nspn=%d but size=%d)\n",
               *nspn, udps[numUdp].arg[narg].size);
    }
}


/*
 ************************************************************************
 *                                                                      *
 *   EG_fitBspline - fit a degree=3 Bspline curve to a set of points    *
 *                                                                      *
 ************************************************************************
 */

static int
EG_fitBspline(ego    context,           /* (in)  EGADS context */
              int    npnt,              /* (in)  number of points */
              int    bitflag,           /* (in)  1=ordered, 2=periodic */
              double xyz[],             /* (in)  array of points (xyzxyz...) */
              int    ncp,               /* (in)  number of control points */
              ego    *ecurve,           /* (out) Bspline curve (degree=3) */
              double *rms)              /* (out) RMS distance of points from curve */
{
    int    status = EGADS_SUCCESS;

    int    nknot, ndata, idata, j, header[4];
    double *cpdata=NULL;

    /* --------------------------------------------------------------- */

    /* default returns */
    *ecurve = NULL;
    *rms    = 0;

    /* check the inputs */
    if (context == NULL) {
        status = EGADS_NULLOBJ;
        goto cleanup;
    } else if (npnt < 2) {
        status = EGADS_NODATA;
        goto cleanup;
    } else if (xyz == NULL) {
        status = EGADS_NODATA;
        goto cleanup;
    } else if (ncp < 3) {
        status = EGADS_NODATA;
        goto cleanup;
    }

    /* set up arrays needed to define Bspline */
    nknot = ncp + 4;
    ndata = nknot + 3 * ncp;

    header[0] = 0;            // bitflag
    header[1] = 3;            // degree
    header[2] = ncp;          // number of control points
    header[3] = nknot;        // number of knots

    cpdata = (double *) malloc(ndata*sizeof(double));
    if (cpdata == NULL) {
        status = EGADS_MALLOC;
        goto cleanup;
    }

    ndata = 0;

    /* knot vector */
    cpdata[ndata++] = 0;
    cpdata[ndata++] = 0;
    cpdata[ndata++] = 0;
    cpdata[ndata++] = 0;

    for (j = 1; j < ncp-3; j++) {
        cpdata[ndata++] = j;
    }

    cpdata[ndata++] = ncp - 3;
    cpdata[ndata++] = ncp - 3;
    cpdata[ndata++] = ncp - 3;
    cpdata[ndata++] = ncp - 3;

    /* control points at the two ends */
    idata = ndata;
    cpdata[idata  ] = xyz[0];
    cpdata[idata+1] = xyz[1];
    cpdata[idata+2] = xyz[2];

    idata = ndata + 3 * (ncp-1);
    cpdata[idata  ] = xyz[3*npnt-3];
    cpdata[idata+1] = xyz[3*npnt-2];
    cpdata[idata+2] = xyz[3*npnt-1];

    /* perform the fitting (which updates the interior control points) */
    status = fit1dCloud(npnt, bitflag, xyz,
                        ncp,  &(cpdata[ndata]), rms);
    if (status < EGADS_SUCCESS) goto cleanup;

    /* make the geometry */
    status = EG_makeGeometry(context, CURVE, BSPLINE, NULL,
                             header, cpdata, ecurve);

cleanup:
    if (cpdata != NULL) free(cpdata);

    return status;
}


/*
 ************************************************************************
 *                                                                      *
 *   fit1dCloud - find spline that best-fits the cloud of points        *
 *                                                                      *
 ************************************************************************
 */

static int
fit1dCloud(int    m,                    /* (in)  number of points in cloud */
           int    bitflag,              /* (in)  1=ordered, 2=periodic */
           double XYZcloud[],           /* (in)  array  of points in cloud */
           int    n,                    /* (in)  number of control points */
           double cp[],                 /* (in)  array  of control points (first and last are set) */
                                        /* (out) array  of control points (all set) */
           double *normf)               /* (out) RMS of distances between cloud and fit */
{
    int    status = EGADS_SUCCESS;      /* (out)  return status */

    int    ordered=0, periodic=0, np, nvar, ivar, jvar, nobj, iobj, i, j, k, next;
    int    niter, iter, count, itol, maxiter;
    double xmin, xmax, ymin, ymax, zmin, zmax, scale, xcent, ycent, zcent;
    double frac, toler, lambda, normdelta, normfnew, delta0, delta1, delta2;
    double XYZ[3], dXYZdT[3], omega, dmax, dist1, dist2, dist;
    double xx, xb, xe, yy, yb, ye, zz, zb, ze, tt, dd, dmin;

    int    *MMi=NULL;
    double *MMd=NULL, errmax;
    double *XYZcopy=NULL, *dXYZdP=NULL, *cpnew=NULL;
    double *beta=NULL, *delta=NULL, *betanew=NULL;
    double *f=NULL,  *fnew=NULL;
    double *aa=NULL, *bb=NULL, *cc=NULL, *rhs=NULL;

    ROUTINE(fit1dCloud);

    /* --------------------------------------------------------------- */

    DPRINT3("enter fit1dCloud(m=%d, bitflag=%d, n=%d)\n", m, bitflag, n);

    assert(m > 1);                      // needed to avoid clang warning
    assert(n > 2);                      // needed to avoid clang warning

    /* default return */
    *normf  = 1e-12;

    /* extract ordered and periodic flags */
    if (bitflag == 1 || bitflag == 3) ordered  = 1;
    if (bitflag == 2 || bitflag == 3) periodic = 1;

    /* number of design variables and objectives */
    np   = 3 * n - 6;
    nvar = m + np;
    nobj = 3 * m;

    /* if m < n, then assume that the linear spline is the best fit */
    if (m < n) {
        for (j = 1; j < n-1; j++) {
            frac = (double)(j) / (double)(n-1);

            cp[3*j  ] = (1-frac) * cp[0] + frac * cp[3*n-3];
            cp[3*j+1] = (1-frac) * cp[1] + frac * cp[3*n-2];
            cp[3*j+2] = (1-frac) * cp[2] + frac * cp[3*n-1];
        }

        DPRINT0("making linear fit because not enough points in cloud\n");
        goto cleanup;
    }

    /* allocate all temporary arrays */
    XYZcopy = (double *) malloc(3*m*sizeof(double));
    dXYZdP  = (double *) malloc(  n*sizeof(double));
    cpnew   = (double *) malloc(3*n*sizeof(double));

    beta    = (double *) malloc(nvar*sizeof(double));
    delta   = (double *) malloc(nvar*sizeof(double));
    betanew = (double *) malloc(nvar*sizeof(double));

    f       = (double *) malloc(nobj*sizeof(double));
    fnew    = (double *) malloc(nobj*sizeof(double));

    aa      = (double *) malloc(m    *sizeof(double));
    bb      = (double *) malloc(m *np*sizeof(double));
    cc      = (double *) malloc(np*np*sizeof(double));
    rhs     = (double *) malloc(nvar *sizeof(double));

    if (XYZcopy == NULL ||dXYZdP == NULL || cpnew == NULL ||
        beta    == NULL || delta == NULL || betanew == NULL ||
        f       == NULL || fnew  == NULL ||
        aa      == NULL || bb    == NULL || cc == NULL || rhs == NULL) {
        status = EGADS_MALLOC;
        goto cleanup;
    }

#define AA(I)       aa[(I)]
#define BB(I,J)     bb[(J)+np*(I)]
#define CC(I,J)     cc[(J)+np*(I)]

    /* transform inputs so that they are centered at origin and
       unit length */
    xmin = XYZcloud[0];
    xmax = XYZcloud[0];
    ymin = XYZcloud[1];
    ymax = XYZcloud[1];
    zmin = XYZcloud[2];
    zmax = XYZcloud[2];

    for (k = 1; k < m; k++) {
        if (XYZcloud[3*k  ] < xmin) xmin = XYZcloud[3*k  ];
        if (XYZcloud[3*k  ] > xmax) xmax = XYZcloud[3*k  ];
        if (XYZcloud[3*k+1] < ymin) ymin = XYZcloud[3*k+1];
        if (XYZcloud[3*k+1] > ymax) ymax = XYZcloud[3*k+1];
        if (XYZcloud[3*k+2] < zmin) zmin = XYZcloud[3*k+2];
        if (XYZcloud[3*k+2] > zmax) zmax = XYZcloud[3*k+2];
    }

    scale = 1.0 / MAX(MAX(xmax-xmin, ymax-ymin), zmax-zmin);
    xcent = scale * (xmin + xmax) / 2;
    ycent = scale * (ymin + ymax) / 2;
    zcent = scale * (zmin + zmax) / 2;

    for (k = 0; k < m; k++) {
        XYZcopy[3*k  ] = scale * (XYZcloud[3*k  ] - xcent);
        XYZcopy[3*k+1] = scale * (XYZcloud[3*k+1] - ycent);
        XYZcopy[3*k+2] = scale * (XYZcloud[3*k+2] - zcent);
    }
    for (j = 0; j < n; j++) {
        cp[3*j  ] = scale * (cp[3*j  ] - xcent);
        cp[3*j+1] = scale * (cp[3*j+1] - ycent);
        cp[3*j+2] = scale * (cp[3*j+2] - zcent);
    }

    /* set up the initial values for the interior control
       points and the initial values of "t" */

    /* XYZcopy is ordered */
    if (ordered == 1) {

        /* set the initial control point locations by picking up evenly
           spaced points (based upon point number) from the cloud */
        for (j = 1; j < n-1; j++) {
            i = (j * (m-1)) / (n-1);

            cp[3*j  ] = XYZcopy[3*i  ];
            cp[3*j+1] = XYZcopy[3*i+1];
            cp[3*j+2] = XYZcopy[3*i+2];
        }

        /* for each point in the cloud, assign the value of "t"
           (which is stored in the first m betas) based upon it
           local pseudo-arc-length */
        beta[0] = 0;
        for (k = 1; k < m; k++) {
            beta[k] = beta[k-1] + sqrt(SQR(XYZcopy[3*k  ]-XYZcopy[3*k-3])
                                      +SQR(XYZcopy[3*k+1]-XYZcopy[3*k-2])
                                      +SQR(XYZcopy[3*k+2]-XYZcopy[3*k-1]));
        }

        for (k = 0; k < m; k++) {
            beta[k] = (n-3) * beta[k] / beta[m-1];
        }

    /* XYZcopy is unordered */
    } else {

        /* set the "center" control point to coincide with the point
           in the cloud that is furthest away from the first and
           last control points */
        dmax = 0;
        for (k = 1; k < m-1; k++) {
            dist1 = pow(XYZcopy[3*k  ]-cp[0], 2)
                  + pow(XYZcopy[3*k+1]-cp[1], 2)
                  + pow(XYZcopy[3*k+2]-cp[2], 2);
            dist2 = pow(XYZcopy[3*k  ]-cp[3*n-3], 2)
                  + pow(XYZcopy[3*k+1]-cp[3*n-2], 2)
                  + pow(XYZcopy[3*k+2]-cp[3*n-1], 2);
            dist  = MIN(dist1, dist2);

            if (dist > dmax) {
                dmax = dist;
                cp[3*(n/2)  ] = XYZcopy[3*k  ];
                cp[3*(n/2)+1] = XYZcopy[3*k+1];
                cp[3*(n/2)+2] = XYZcopy[3*k+2];
            }
        }

        /* fill in the other control points */
        for (j = 1; j < (n/2); j++) {
            frac = (double)(j) / (double)(n/2);

            cp[3*j  ] = (1-frac) * cp[0] + frac * cp[3*(n/2)  ];
            cp[3*j+1] = (1-frac) * cp[1] + frac * cp[3*(n/2)+1];
            cp[3*j+2] = (1-frac) * cp[2] + frac * cp[3*(n/2)+2];
        }

        for (j = (n/2)+1; j < n; j++) {
            frac = (double)(j-(n/2)) / (double)(n-1-(n/2));

            cp[3*j  ] = (1-frac) * cp[3*(n/2)  ] + frac * cp[3*n-3];
            cp[3*j+1] = (1-frac) * cp[3*(n/2)+1] + frac * cp[3*n-2];
            cp[3*j+2] = (1-frac) * cp[3*(n/2)+2] + frac * cp[3*n-1];
        }

        /* for each point in the cloud, assign the value of "t"
           (which is stored in the first m betas) as the closest
           point to the control polygon */
        for (k = 0; k < m; k++) {
            xx = XYZcopy[3*k  ];
            yy = XYZcopy[3*k+1];
            zz = XYZcopy[3*k+2];

            dmin = HUGEQ;
            for (j = 1; j < n; j++) {
                xb = cp[3*j-3];   yb = cp[3*j-2];   zb = cp[3*j-1];
                xe = cp[3*j  ];   ye = cp[3*j+1];   ze = cp[3*j+2];

                tt = ((xe-xb) * (xx-xb) + (ye-yb) * (yy-yb) + (ze-zb) * (zz-zb))
                   / ((xe-xb) * (xe-xb) + (ye-yb) * (ye-yb) + (ze-zb) * (ze-zb));
                tt = MIN(MAX(0, tt), 1);

                dd = pow((1-tt) * xb + tt * xe - xx, 2)
                   + pow((1-tt) * yb + tt * ye - yy, 2)
                   + pow((1-tt) * zb + tt * ze - zz, 2);

                if (dd < dmin) {
                    dmin    = dd;
                    beta[k] = ((j-1) + tt) * (double)(n - 3) / (double)(n - 1);
                }
            }
        }
    }

#ifdef DEBUG
    printf("Initialization\n");
    for (j = 0; j < n; j++) {
        printf("%3d: %12.6f %12.6f %12.6f\n", j, cp[3*j], cp[3*j+1], cp[3*j+2]);
    }
    for (k = 0; k < m; k++) {
        printf("%3d: %12.6f\n", k, beta[k]);
    }
#endif

    /* set the relaxation parameter for control points */
    omega = 0.25;

    /* insert the interior control points into the design variables */
    next = m;
    for (j = 1; j < n-1; j++) {
        beta[next++] = cp[3*j  ];
        beta[next++] = cp[3*j+1];
        beta[next++] = cp[3*j+2];
    }

    /* compute the initial objective function */
    for (k = 0; k < m; k++) {
        status = eval1dBspline(beta[k], n, cp, XYZ, NULL, NULL);
        CHECK_STATUS(eval1dBspline);

        f[3*k  ] = XYZcopy[3*k  ] - XYZ[0];
        f[3*k+1] = XYZcopy[3*k+1] - XYZ[1];
        f[3*k+2] = XYZcopy[3*k+2] - XYZ[2];
    }
    *normf = L2norm(f, nobj) / m;
    DPRINT1("initial   norm(f)=%11.4e\n", *normf);

    /* initialize the Levenberg-Marquardt algorithm */
    niter  = 501;
    toler  = 1.0e-6;
    lambda = 1;

    /* LM iterations */
    for (iter = 0; iter < niter; iter++) {

        /* initialize [AA  BB]
                      [      ] =  transpose(J) * J + lambda * diag(transpose(J) * J)
                      [BB' CC]

           and        rhs  = -transpose(J) * f
        */
        for (jvar = 0; jvar < np; jvar++) {
            for (ivar = 0; ivar < np; ivar++) {
                CC(ivar,jvar) = 0;
            }
            CC(jvar,jvar) = 1e-6;
        }

        for (jvar = 0; jvar < nvar; jvar++) {
            rhs[jvar] = 0;
        }

        /* accumulate AA, BB, CC, and rhs by looping over points in cloud */
        for (k = 0; k < m; k++) {
            status = eval1dBspline(beta[k], n, cp, XYZ, dXYZdT, dXYZdP);
            CHECK_STATUS(eval1dBspline);

            AA(k) = dXYZdT[0] * dXYZdT[0] + dXYZdT[1] * dXYZdT[1] + dXYZdT[2] * dXYZdT[2];

            for (ivar = 1; ivar < n-1; ivar++) {
                BB(k, 3*ivar-3) = dXYZdT[0] * dXYZdP[ivar];
                BB(k, 3*ivar-2) = dXYZdT[1] * dXYZdP[ivar];
                BB(k, 3*ivar-1) = dXYZdT[2] * dXYZdP[ivar];

                for (jvar = 1; jvar < n-1; jvar++) {
#ifndef __clang_analyzer__
                    CC(3*ivar-3, 3*jvar-3) += dXYZdP[ivar] * dXYZdP[jvar];
                    CC(3*ivar-2, 3*jvar-2) += dXYZdP[ivar] * dXYZdP[jvar];
                    CC(3*ivar-1, 3*jvar-1) += dXYZdP[ivar] * dXYZdP[jvar];
#endif
                }
            }

            rhs[k] = dXYZdT[0] * f[3*k] + dXYZdT[1] * f[3*k+1] + dXYZdT[2] * f[3*k+2];

            for (ivar = 1; ivar < n-1; ivar++) {
#ifndef __clang_analyzer__
                rhs[m+3*ivar-3] += dXYZdP[ivar] * f[3*k  ];
                rhs[m+3*ivar-2] += dXYZdP[ivar] * f[3*k+1];
                rhs[m+3*ivar-1] += dXYZdP[ivar] * f[3*k+2];
#endif
            }
        }

        /* set up sparse-matrix arrays */
        count = m + 2 * m * np + np * np + 1;

        MMd = (double *) malloc(count*sizeof(double));
        MMi = (int    *) malloc(count*sizeof(int   ));

        if (MMd == NULL || MMi == NULL) {
            status = EGADS_MALLOC;
            goto cleanup;
        }

        /* store diagonal values (multiplied by (1+lambda)) */
        for (k = 0; k < m; k++) {
            MMd[k] = AA(k) * (1 + lambda);
        }
        for (ivar = 0; ivar < np; ivar++) {
            MMd[m+ivar] = CC(ivar,ivar) * (1 + lambda);
        }

        /* set up off-diagonal elements, including indices */
        MMi[0] = nvar + 1;
        count  = nvar;

        /* BB to the right of AA */
        for (k = 0; k < m; k++) {
            for (jvar = 0; jvar < np; jvar++) {
                count++;
                MMd[count] = BB(k,jvar);
                MMi[count] = m + jvar;
            }
            MMi[k+1] = count + 1;
        }

        for (ivar = 0; ivar < np; ivar++) {
            /* transpose(BB) below A */
            for (k = 0; k < m; k++) {
                count++;
                MMd[count] = BB(k,ivar);
                MMi[count] = k;
            }

            /* CC in bottom-right corner */
            for (jvar = 0; jvar < np; jvar++) {
                if (ivar != jvar) {
                    count++;
                    MMd[count] = CC(ivar,jvar);
                    MMi[count] = m + jvar;
                }
            }
            MMi[m+ivar+1] = count + 1;
        }

        /* arbitrary value (not used) */
        MMd[nvar] = 0;

        /* set up for sparse matrix solve (via biconjugate gradient technique) */
        itol    = 1;
        errmax  = 1.0e-12;
        maxiter = 2 * nvar;
        for (ivar = 0; ivar < nvar; ivar++) {
            delta[ivar] = 0;
        }

        status = solveSparse(MMd, MMi, rhs, delta, itol, &errmax, &maxiter);
        CHECK_STATUS(solveSparse);

        FREE(MMd);
        FREE(MMi);

        /* check for convergence on delta (which corresponds to a small
           change in beta) */
        normdelta = L2norm(delta, nvar);

        if (normdelta < toler) {
            DPRINT1("converged with norm(delta)=%11.4e\n", normdelta);
            break;
        }

        /* find the temporary new beta */
        for (ivar = 0; ivar < nvar; ivar++) {

            /* beta associated with Tcloud */
            if (ivar < m) {
                betanew[ivar] = beta[ivar] + delta[ivar];

                if (betanew[ivar] < 0  ) betanew[ivar] = 0;
                if (betanew[ivar] > n-3) betanew[ivar] = n-3;

                /* beta associated with control points */
            } else {
                betanew[ivar] = beta[ivar] + omega * delta[ivar];
            }
        }

        /* gradually increase omega */
        omega = MIN(1.01*omega, 1.0);

        /* extract the temporary control points from betanew */
        next = m;
        for (j = 0; j < n; j++) {
            if (j == 0 || j == n-1) {
                cpnew[3*j  ] = cp[3*j  ];
                cpnew[3*j+1] = cp[3*j+1];
                cpnew[3*j+2] = cp[3*j+2];
            } else {
                cpnew[3*j  ] = betanew[next++];
                cpnew[3*j+1] = betanew[next++];
                cpnew[3*j+2] = betanew[next++];
            }
        }

        /* apply periodicity condition by making sure first and last
           intervals are the same */
        if (periodic == 1) {
            delta0 = (2*cpnew[0] - cpnew[3] - cpnew[3*n-6]) / 2;
            delta1 = (2*cpnew[1] - cpnew[4] - cpnew[3*n-5]) / 2;
            delta2 = (2*cpnew[2] - cpnew[5] - cpnew[3*n-4]) / 2;

            cpnew[    3] += delta0;
            cpnew[    4] += delta1;
            cpnew[    5] += delta2;

            cpnew[3*n-6] += delta0;
            cpnew[3*n-5] += delta1;
            cpnew[3*n-4] += delta2;
        }

        /* compute the objective function based upon the new beta */
        for (k = 0; k < m; k++) {
            status = eval1dBspline(betanew[k], n, cp, XYZ, NULL, NULL);
            CHECK_STATUS(eval1dBspline);

            fnew[3*k  ] = XYZcopy[3*k  ] - XYZ[0];
            fnew[3*k+1] = XYZcopy[3*k+1] - XYZ[1];
            fnew[3*k+2] = XYZcopy[3*k+2] - XYZ[2];
        }
        normfnew = L2norm(fnew, nobj) / m;
        if (iter%10 == 0) {
            DPRINT3("iter=%4d: norm(delta)=%11.4e, norm(f)=%11.4e  ",
                   iter, normdelta, normfnew);
        }

        /* if this was a better step, accept it and decrease
           lambda (making it more Newton-like) */
        if (normfnew < *normf) {
            lambda /= 2;
            if (iter%10 == 0) {
                DPRINT2("ACCEPTED,  lambda=%11.4e, omega=%10.5f\n", lambda, omega);
            }

            /* save new design variables, control points, and
               objective function */
            for (ivar = 0; ivar < nvar; ivar++) {
                beta[ivar] = betanew[ivar];
            }
            for (j = 0; j < n; j++) {
                cp[3*j  ] = cpnew[3*j  ];
                cp[3*j+1] = cpnew[3*j+1];
                cp[3*j+2] = cpnew[3*j+2];
            }
            for (iobj = 0; iobj < nobj; iobj++) {
                f[iobj] = fnew[iobj];
            }
            *normf = normfnew;

        /* otherwise do not take the step and increase lambda (making it
           more steepest-descent-like) */
        } else {
            lambda *= 2;
            if (iter %10 == 0) {
                DPRINT2("rejected,  lambda=%11.4e, omega=%10.5f\n", lambda, omega);
            }
        }

        /* check for convergence (based upon a small value of
           objective function) */
        if (*normf < toler) {
            DPRINT1("converged with norm(f)=%11.4e\n", *normf);
            break;
        }
    }

    /* transform control points back to their original scale */
    for (j = 0; j < n; j++) {
        cp[3*j  ] = xcent + cp[3*j  ] / scale;
        cp[3*j+1] = ycent + cp[3*j+1] / scale;
        cp[3*j+2] = zcent + cp[3*j+2] / scale;
    }

    *normf /= scale;

#ifdef DEBUG
    printf("final control points\n");
    for (j = 0; j < n; j++) {
        printf("%3d: %12.6f %12.6f %12.6f\n", j, cp[3*j], cp[3*j+1], cp[3*j+2]);
    }
    printf("*normf: %12.4e\n", *normf);
#endif

cleanup:
    if (XYZcopy != NULL) free(XYZcopy);
    if (dXYZdP  != NULL) free(dXYZdP );
    if (cpnew   != NULL) free(cpnew  );

    if (beta    != NULL) free(beta   );
    if (delta   != NULL) free(delta  );
    if (betanew != NULL) free(betanew);

    if (f       != NULL) free(f      );
    if (fnew    != NULL) free(fnew   );

    if (aa      != NULL) free(aa     );
    if (bb      != NULL) free(bb     );
    if (cc      != NULL) free(cc     );
    if (rhs     != NULL) free(rhs    );

    if (MMi     != NULL) free(MMi    );
    if (MMd     != NULL) free(MMd    );

#undef AA
#undef BB
#undef CC

    return status;
}


/*
 ************************************************************************
 *                                                                      *
 *   eval1dBspline - evaluate cubic Bspline and its derivatives         *
 *                                                                      *
 ************************************************************************
 */

static int
eval1dBspline(double T,                 /* (in)  independent variable */
              int    n,                 /* (in)  number of control points */
              double cp[],              /* (in)  array  of control points */
              double XYZ[],             /* (out) dependent variables */
    /*@null@*/double dXYZdT[],          /* (out) derivative wrt T (or NULL) */
    /*@null@*/double dXYZdP[])          /* (out) derivative wrt P (or NULL) */
{
    int    status = EGADS_SUCCESS;      /* (out) return status */

    int    i, span;
    double N[4], dN[4];

    ROUTINE(eval1dBspline);

    /* --------------------------------------------------------------- */

    assert (n > 3);

    XYZ[0] = 0;
    XYZ[1] = 0;
    XYZ[2] = 0;

    /* set up the Bspline bases */
    status = cubicBsplineBases(n, T, N, dN);
    CHECK_STATUS(cubicBsplineBases);

    span = MIN(floor(T), n-4);

    /* find the dependent variable */
    for (i = 0; i < 4; i++) {
        XYZ[0] += N[i] * cp[3*(i+span)  ];
        XYZ[1] += N[i] * cp[3*(i+span)+1];
        XYZ[2] += N[i] * cp[3*(i+span)+2];
    }

    /* find the deriviative wrt T */
    if (dXYZdT != NULL) {
        dXYZdT[0] = 0;
        dXYZdT[1] = 0;
        dXYZdT[2] = 0;

        for (i = 0; i < 4; i++) {
            dXYZdT[0] += dN[i] * cp[3*(i+span)  ];
            dXYZdT[1] += dN[i] * cp[3*(i+span)+1];
            dXYZdT[2] += dN[i] * cp[3*(i+span)+2];
        }
    }

    /* find the derivative wrt P */
    if (dXYZdP != NULL) {
        for (i = 0; i < n; i++) {
            dXYZdP[i] = 0;
        }
        for (i = 0; i < 4; i++) {
            dXYZdP[i+span] += N[i];
        }
    }

cleanup:
    return status;
}


/*
 ************************************************************************
 *                                                                      *
 *   cubicBsplineBases - basis function values for cubic Bspline        *
 *                                                                      *
 ************************************************************************
 */

static int
cubicBsplineBases(int    ncp,           /* (in)  number of control points */
                  double T,             /* (in)  independent variable (0<=T<=(ncp-3) */
                  double N[],           /* (out) bases */
                  double dN[])          /* (out) d(bases)/d(T) */
{
    int       status = EGADS_SUCCESS;   /* (out) return status */

    int      i, r, span;
    double   saved, dsaved, num, dnum, den, dden, temp, dtemp;
    double   left[4], dleft[4], rite[4], drite[4];

    ROUTINE(cubicBsplineBases);

    /* --------------------------------------------------------------- */

    span = MIN(floor(T)+3, ncp-1);

    N[ 0] = 1.0;
    dN[0] = 0;

    for (i = 1; i <= 3; i++) {
        left[ i] = T - MAX(0, span-2-i);
        dleft[i] = 1;

        rite[ i] = MIN(ncp-3,span-3+i) - T;
        drite[i] =                     - 1;

        saved  = 0;
        dsaved = 0;

        for (r = 0; r < i; r++) {
            num   = N[ r];
            dnum  = dN[r];

            den   = rite[ r+1] + left[ i-r];
            dden  = drite[r+1] + dleft[i-r];

            temp  = num / den;
            dtemp = (dnum * den - dden * num) / den / den;

            N[ r] = saved  + rite[ r+1] * temp;
            dN[r] = dsaved + drite[r+1] * temp + rite[r+1] * dtemp;

            saved  = left[ i-r] * temp;
            dsaved = dleft[i-r] * temp + left[i-r] * dtemp;
        }

        N[ i] = saved;
        dN[i] = dsaved;
    }

//cleanup:
    return status;
}


/*
 ************************************************************************
 *                                                                      *
 *   solveSparse - solve: A * x = b  using biconjugate gradient method  *
 *                                                                      *
 ************************************************************************
 */

static int
solveSparse(double SAv[],               /* (in)  sparse array values */
            int    SAi[],               /* (in)  sparse array indices */
            double b[],                 /* (in)  rhs vector */
            double x[],                 /* (in)  guessed result vector */
                                        /* (out) result vector */
            int    itol,                /* (in)  stopping criterion */
            double *errmax,             /* (in)  convergence tolerance */
                                        /* (out) estimated error at convergence */
            int    *iter)               /* (in)  maximum number of iterations */
                                        /* (out) number of iterations taken */
{
    int    status = EGADS_SUCCESS;      /* (out) return status */

    int    n, i, j, k, itmax;
    double tol, ak, akden, bk, bknum, bkden=1, bnorm, dxnorm, xnorm, znorm_old, znorm=0;
    double *p=NULL, *pp=NULL, *r=NULL, *rr=NULL, *z=NULL, *zz=NULL;

    ROUTINE(solveSparse);

    /* --------------------------------------------------------------- */

    tol   = *errmax;
    itmax = *iter;

    n = SAi[0] - 1;

    p  = (double *) malloc(n*sizeof(double));
    pp = (double *) malloc(n*sizeof(double));
    r  = (double *) malloc(n*sizeof(double));
    rr = (double *) malloc(n*sizeof(double));
    z  = (double *) malloc(n*sizeof(double));
    zz = (double *) malloc(n*sizeof(double));

    if (p == NULL || pp == NULL ||
        r == NULL || rr == NULL ||
        z == NULL || zz == NULL   ) {
        status = EGADS_MALLOC;
        goto cleanup;
    }

    /* make sure none of the diagonals are very small */
    for (i = 0; i < n; i++) {
        if (fabs(SAv[i]) < 1.0e-14) {
            printf(" solveSparse: cannot solve since SAv[%d]=%11.4e\n", i, SAv[i]);
            status = EGADS_DEGEN;
            goto cleanup;
        }
    }

    /* calculate initial residual */
    *iter = 0;

    /* r = A * x  */
    for (i = 0; i < n; i++) {
        r[i] = SAv[i] * x[i];

        for (k = SAi[i]; k < SAi[i+1]; k++) {
            r[i] += SAv[k] * x[SAi[k]];
        }
    }

    for (j = 0; j < n; j++) {
        r[ j] = b[j] - r[j];
        rr[j] = r[j];
    }

    if (itol == 1) {
        bnorm = L2norm(b, n);

        for (j = 0; j < n; j++) {
            z[j] = r[j] / SAv[j];
        }
    } else if (itol == 2) {
        for (j = 0; j < n; j++) {
            z[j] = b[j] / SAv[j];
        }

        bnorm = L2norm(z, n);

        for (j = 0; j < n; j++) {
            z[j] = r[j] / SAv[j];
        }
    } else {
        for (j = 0; j < n; j++) {
            z[j] = b[j] / SAv[j];
        }

        bnorm = L2norm(z, n);

        for (j = 0; j < n; j++) {
            z[j] = r[j] / SAv[j];
        }

        znorm = L2norm(z, n);
    }

    /* main iteration loop */
    for (*iter = 0; *iter < itmax; (*iter)++) {

        for (j = 0; j < n; j++) {
            zz[j] = rr[j] / SAv[j];
        }

        /* calculate coefficient bk and direction vectors p and pp */
        bknum = 0;
        for (j = 0; j < n; j++) {
            bknum += z[j] * rr[j];
        }

        if (*iter == 0) {
            for (j = 0; j < n; j++) {
                p[ j] = z[ j];
                pp[j] = zz[j];
            }
        } else {
            bk = bknum / bkden;

            for (j = 0; j < n; j++) {
                p[ j] = bk * p[ j] + z[ j];
                pp[j] = bk * pp[j] + zz[j];
            }
        }

        /* calculate coefficient ak, new iterate x, and new residuals r and rr */
        bkden = bknum;

        /* z = A * p  */
        for (i = 0; i < n; i++) {
            z[i] = SAv[i] * p[i];

            for (k = SAi[i]; k < SAi[i+1]; k++) {
                z[i] += SAv[k] * p[SAi[k]];
            }
        }

        akden = 0;
        for (j = 0; j < n; j++) {
            akden += z[j] * pp[j];
        }

        ak = bknum / akden;

        /* zz = transpose(A) * pp  */
        for (i = 0; i < n; i++) {
            zz[i] = SAv[i] * pp[i];
        }

        for (i = 0; i < n; i++) {
            for (k = SAi[i]; k < SAi[i+1]; k++) {
                j = SAi[k];
                zz[j] += SAv[k] * pp[i];
            }
        }

        for (j = 0; j < n; j++) {
            x[ j] += ak * p[ j];
            r[ j] -= ak * z[ j];
            rr[j] -= ak * zz[j];
        }

        /* solve Abar * z = r */
        for (j = 0; j < n; j++) {
            z[j] = r[j] / SAv[j];
        }

        /* compute and check stopping criterion */
        if (itol == 1) {
            *errmax = L2norm(r, n) / bnorm;
        } else if (itol == 2) {
            *errmax = L2norm(z, n) / bnorm;
        } else {
            znorm_old = znorm;
            znorm = L2norm(z, n);
            if (fabs(znorm_old-znorm) > (1.0e-14)*znorm) {
                dxnorm = fabs(ak) * L2norm(p, n);
                *errmax  = znorm / fabs(znorm_old-znorm) * dxnorm;
            } else {
                *errmax = znorm / bnorm;
                continue;
            }

            xnorm = L2norm(x, n);
            if (*errmax <= xnorm/2) {
                *errmax /= xnorm;
            } else {
                *errmax = znorm / bnorm;
                continue;
            }
        }

        /* exit if converged */
        if (*errmax <= tol) break;
    }

cleanup:
    if (p  != NULL) free(p );
    if (pp != NULL) free(pp);
    if (r  != NULL) free(r );
    if (rr != NULL) free(rr);
    if (z  != NULL) free(z );
    if (zz != NULL) free(zz);

    return status;
}


/*
 ************************************************************************
 *                                                                      *
 *   L2norm - L2-norm of vector                                         *
 *                                                                      *
 ************************************************************************
 */

static double
L2norm(double f[],                      /* (in)  vector */
       int    n)                        /* (in)  length of vector */
{
    double L2norm;                      /* (out) L2-norm */

    int    i;

    ROUTINE(L2norm);

    /* --------------------------------------------------------------- */

    /* L2-norm */
    L2norm = 0;

    for (i = 0; i < n; i++) {
        L2norm += f[i] * f[i];
    }

    L2norm = sqrt(L2norm);

//cleanup:
    return L2norm;
}


/*
 ************************************************************************
 *                                                                      *
 *   plotCurve - plot geometry, control polygon, and fit                *
 *                                                                      *
 ************************************************************************
 */

#ifdef GRAFIC
static int
plotCurve(int    npnt,                  /* (in)  number of points in cloud */
          double xyz[],                 /* (in)  points in cloud */
          ego    ecurve)                /* (in)  Curve */
{
    int    status = EGADS_SUCCESS;

    int    io_kbd=5, io_scr=6, nline=0, nplot=0;
    int    indgr=1+2+4+16+64, periodic, oclass, mtype, *tempIlist, icp, ipnt;
    int    ilin[3], isym[3], nper[3], ncp;
    float  *xplot=NULL, *yplot=NULL, *zplot=NULL;
    double xmin, xmax, ymin, ymax, zmin, zmax, trange[4], frac, tt, data[18];
    double *tempRlist;
    ego    eref;

    /* --------------------------------------------------------------- */

    xplot = (float*) malloc((npnt+2000)*sizeof(float));
    yplot = (float*) malloc((npnt+2000)*sizeof(float));
    zplot = (float*) malloc((npnt+2000)*sizeof(float));

    if (xplot == NULL || yplot == NULL || zplot == NULL) {
        status = EGADS_MALLOC;
        goto cleanup;
    }

    xmin = xyz[0];
    xmax = xyz[0];
    ymin = xyz[1];
    ymax = xyz[1];
    zmin = xyz[2];
    zmax = xyz[2];

    /* build plot arrays for data points */
    for (ipnt = 0; ipnt < npnt; ipnt++) {
        xplot[nplot] = xyz[3*ipnt  ];
        yplot[nplot] = xyz[3*ipnt+1];
        zplot[nplot] = xyz[3*ipnt+2];
        nplot++;

        if (xyz[3*ipnt  ] < xmin) xmin = xyz[3*ipnt  ];
        if (xyz[3*ipnt  ] > xmax) xmax = xyz[3*ipnt  ];
        if (xyz[3*ipnt+1] < ymin) ymin = xyz[3*ipnt+1];
        if (xyz[3*ipnt+1] > ymax) ymax = xyz[3*ipnt+1];
        if (xyz[3*ipnt+2] < zmin) zmin = xyz[3*ipnt+2];
        if (xyz[3*ipnt+2] > zmax) zmax = xyz[3*ipnt+2];
    }

    ilin[nline] = -GR_DASHED;
    isym[nline] = +GR_CIRCLE;
    nper[nline] = npnt;
    nline++;

    /* build plot arrays for fit */
    status = EG_getRange(ecurve, trange, &periodic);
    if (status != EGADS_SUCCESS) goto cleanup;

    for (ipnt = 0; ipnt < 1000; ipnt++) {
        frac = (double)(ipnt) / (double)(1000-1);
        tt   = (1-frac) * trange[0] + frac * trange[1];

        status = EG_evaluate(ecurve, &tt, data);
        if (status != EGADS_SUCCESS) goto cleanup;

        xplot[nplot] = data[0];
        yplot[nplot] = data[1];
        zplot[nplot] = data[2];
        nplot++;
    }

    ilin[nline] = +GR_SOLID;
    isym[nline] = -GR_PLUS;
    nper[nline] = 1000;
    nline++;

    /* build plot arrays for control points */
    status = EG_getGeometry(ecurve, &oclass, &mtype, &eref, &tempIlist, &tempRlist);
    if (status != EGADS_SUCCESS) goto cleanup;
    if (oclass != CURVE        ) goto cleanup;
    if (mtype  != BSPLINE      ) goto cleanup;

    ncp = tempIlist[2];

    for (icp = 0; icp < ncp; icp++) {
        xplot[nplot] = tempRlist[tempIlist[3]+3*icp  ];
        yplot[nplot] = tempRlist[tempIlist[3]+3*icp+1];
        zplot[nplot] = tempRlist[tempIlist[3]+3*icp+2];
        nplot++;
    }

    ilin[nline] = +GR_DOTTED;
    isym[nline] = +GR_SQUARE;
    nper[nline] = ncp;
    nline++;

    /* generate plot */
    if        (xmin == xmax) {
        grinit_(&io_kbd, &io_scr, "udpFitcurve", strlen("udpFitcurve"));

        grline_(ilin, isym, &nline,                "~y~z~O=inputs, --=fit, ...=cp",
                &indgr, yplot, zplot, nper, strlen("~y~z~O=inputs, --=fit, ...=cp"));

    } else if (ymin == ymax) {
        grinit_(&io_kbd, &io_scr, "udpFitcurve", strlen("udpFitcurve"));

        grline_(ilin, isym, &nline,                "~z~x~O=inputs, --=fit, ...=cp",
                &indgr, zplot, xplot, nper, strlen("~z~x~O=inputs, --=fit, ...=cp"));

    } else {
        grinit_(&io_kbd, &io_scr, "udpFitcurve", strlen("udpFitcurve"));

        grline_(ilin, isym, &nline,                "~x~y~O=inputs, --=fit, ...=cp",
                &indgr, xplot, yplot, nper, strlen("~x~y~O=inputs, --=fit, ...=cp"));
    }

cleanup:
    if (xplot != NULL) free(xplot);
    if (yplot != NULL) free(yplot);
    if (zplot != NULL) free(zplot);

    return status;
}
#endif
