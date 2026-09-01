/* C-ABI bridge to MeshFix (IMATI-GE / CNR, GPLv3).
 *
 * MeshFix is a C++ command-line program, not a library: it builds meshes only
 * from files, and it calls exit() when it gives up. This shim wraps it so it
 * can be driven from Swift with in-memory arrays and reports failure by
 * returning instead of terminating the process.
 */
#ifndef MESHFIX_SHIM_H
#define MESHFIX_SHIM_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Repaired geometry. Free with meshfix_free(). */
typedef struct {
    double  *vertices;      /* 3 doubles per vertex   */
    int32_t  vertex_count;
    int32_t *faces;         /* 3 indices per triangle */
    int32_t  face_count;
} MFMesh;

enum {
    MF_OK = 0,
    MF_BAD_INPUT = 1,       /* nothing usable was handed in            */
    MF_EMPTY_RESULT = 2,    /* MeshFix consumed the mesh entirely      */
    MF_FAILED = 3           /* MeshFix reported an error and gave up   */
};

/* Repairs one mesh.
 *
 * join_components != 0 fuses separate shells into a single solid; otherwise
 * only the largest shell survives, which is MeshFix's own default.
 *
 * Returns MF_OK and fills `out` on success. On failure `out` is left zeroed
 * and, when `error` is non-null, a NUL-terminated description is written to it.
 */
int meshfix_repair(const double *vertices, int32_t vertex_count,
                   const int32_t *faces, int32_t face_count,
                   int join_components,
                   MFMesh *out,
                   char *error, int32_t error_capacity);

void meshfix_free(MFMesh *mesh);

/* Version string of the vendored MeshFix. */
const char *meshfix_version(void);

#ifdef __cplusplus
}
#endif

#endif /* MESHFIX_SHIM_H */
