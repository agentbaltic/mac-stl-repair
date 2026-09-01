// C-ABI bridge to MeshFix. See include/meshfix_shim.h.
//
// Three things have to be worked around to embed MeshFix in an app:
//
//  1. It builds meshes only from files. ArrayMesh subclasses Basic_TMesh so it
//     can reach the protected loading machinery and build from arrays instead.
//  2. TMesh::error() calls exit(-1) unless a display_message hook is installed.
//     We install one that throws, and catch it here.
//  3. joinClosestComponents() lives in meshfix.cpp next to main(), which we
//     cannot compile into a library, so it is reproduced below.

#include "meshfix_shim.h"

#include "tmesh.h"
#include "tin.h"

#include <cfloat>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <new>
#include <string>

using namespace T_MESH;

// io.cpp keeps these private; restated so extract() can read indices back.
#define SHIM_TVI1(a) (TMESH_TO_INT(((Triangle *)(a)->data)->v1()->x))
#define SHIM_TVI2(a) (TMESH_TO_INT(((Triangle *)(a)->data)->v2()->x))
#define SHIM_TVI3(a) (TMESH_TO_INT(((Triangle *)(a)->data)->v3()->x))

namespace {

// Thrown from the message hook so a MeshFix error unwinds instead of exiting.
struct MeshFixAbort : std::exception {
    std::string message;
    explicit MeshFixAbort(const char *m) : message(m ? m : "MeshFix failed") {}
    const char *what() const noexcept override { return message.c_str(); }
};

void messageHook(const char *text, int action) {
    if (action == DISPMSG_ACTION_ERRORDIALOG) throw MeshFixAbort(text);
}

// Basic_TMesh's array-building path is protected, so reach it by inheritance.
class ArrayMesh : public Basic_TMesh {
public:
    // Mirrors what the file loaders do: append vertices, wrap them in
    // ExtVertex handles, create indexed triangles, then fix connectivity.
    bool build(const double *verts, int32_t nv, const int32_t *tris, int32_t nf) {
        for (int32_t i = 0; i < nv; i++)
            V.appendTail(newVertex(verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2]));

        ExtVertex **var = (ExtVertex **)malloc(sizeof(ExtVertex *) * (size_t)nv);
        if (var == NULL) return false;
        Node *n; Vertex *v; int32_t i = 0;
        FOREACHVERTEX(v, n) var[i++] = new ExtVertex(v);

        int32_t created = 0;
        for (int32_t t = 0; t < nf; t++) {
            const int32_t a = tris[t * 3], b = tris[t * 3 + 1], c = tris[t * 3 + 2];
            if (a == b || b == c || c == a) continue;          // degenerate
            if (a < 0 || b < 0 || c < 0) continue;
            if (a >= nv || b >= nv || c >= nv) continue;       // out of range
            if (CreateIndexedTriangle(var, a, b, c)) created++;
        }

        for (int32_t k = 0; k < nv; k++) delete var[k];
        free(var);

        if (created == 0) return false;
        fixConnectivity();
        d_boundaries = d_handles = d_shells = 1;
        return true;
    }

    // MeshFix's own idiom for reading indices back out (see io.cpp): stash each
    // vertex's x coordinate, overwrite it with the vertex's ordinal so the TVI*
    // macros resolve to indices, then put the coordinates back.
    bool extract(MFMesh *out) {
        const int nv = V.numels();
        const int nf = T.numels();
        if (nv <= 0 || nf <= 0) return false;

        double *vertices = (double *)malloc(sizeof(double) * (size_t)nv * 3);
        int32_t *faces = (int32_t *)malloc(sizeof(int32_t) * (size_t)nf * 3);
        coord *saved = new (std::nothrow) coord[nv];
        if (vertices == NULL || faces == NULL || saved == NULL) {
            free(vertices); free(faces); delete[] saved;
            return false;
        }

        Node *n; Vertex *v;
        int i = 0;
        FOREACHVERTEX(v, n) {
            vertices[i * 3]     = TMESH_TO_DOUBLE(v->x);
            vertices[i * 3 + 1] = TMESH_TO_DOUBLE(v->y);
            vertices[i * 3 + 2] = TMESH_TO_DOUBLE(v->z);
            saved[i] = v->x;
            i++;
        }
        i = 0;
        FOREACHVERTEX(v, n) v->x = i++;

        i = 0;
        FOREACHNODE(T, n) {
            faces[i * 3]     = (int32_t)SHIM_TVI1(n);
            faces[i * 3 + 1] = (int32_t)SHIM_TVI2(n);
            faces[i * 3 + 2] = (int32_t)SHIM_TVI3(n);
            i++;
        }

        i = 0;
        FOREACHVERTEX(v, n) v->x = saved[i++];
        delete[] saved;

        out->vertices = vertices;
        out->vertex_count = (int32_t)nv;
        out->faces = faces;
        out->face_count = (int32_t)nf;
        return true;
    }
};

double closestPair(List *bl1, List *bl2, Vertex **onFirst, Vertex **onSecond) {
    Node *n, *m;
    Vertex *v, *w;
    double adist, mindist = DBL_MAX;
    FOREACHVVVERTEX(bl1, v, n)
        FOREACHVVVERTEX(bl2, w, m)
            if ((adist = w->squaredDistance(v)) < mindist) {
                mindist = adist;
                *onFirst = v;
                *onSecond = w;
            }
    return mindist;
}

// Verbatim from MeshFix's meshfix.cpp, which cannot be linked in (it has main).
bool joinClosestComponents(Basic_TMesh *tin) {
    Vertex *v, *w, *gv, *gw;
    Triangle *t, *s;
    Node *n;
    List triList, boundary_loops, *one_loop;
    List **bloops_array;
    int i, j, numloops;

    i = 0;
    FOREACHVTTRIANGLE((&(tin->T)), t, n) t->info = NULL;
    FOREACHVTTRIANGLE((&(tin->T)), t, n) if (t->info == NULL) {
        i++;
        triList.appendHead(t);
        t->info = (void *)(intptr_t)i;
        while (triList.numels()) {
            t = (Triangle *)triList.popHead();
            if ((s = t->t1()) != NULL && s->info == NULL) { triList.appendHead(s); s->info = (void *)(intptr_t)i; }
            if ((s = t->t2()) != NULL && s->info == NULL) { triList.appendHead(s); s->info = (void *)(intptr_t)i; }
            if ((s = t->t3()) != NULL && s->info == NULL) { triList.appendHead(s); s->info = (void *)(intptr_t)i; }
        }
    }

    if (i < 2) {
        FOREACHVTTRIANGLE((&(tin->T)), t, n) t->info = NULL;
        return false;
    }

    FOREACHVTTRIANGLE((&(tin->T)), t, n) {
        t->v1()->info = t->v2()->info = t->v3()->info = t->info;
    }

    FOREACHVVVERTEX((&(tin->V)), v, n) if (!IS_VISITED2(v) && v->isOnBoundary()) {
        w = v;
        one_loop = new List;
        do {
            one_loop->appendHead(w); MARK_VISIT2(w);
            w = w->nextOnBoundary();
        } while (w != v);
        boundary_loops.appendHead(one_loop);
    }
    FOREACHVVVERTEX((&(tin->V)), v, n) UNMARK_VISIT2(v);

    bloops_array = (List **)boundary_loops.toArray();
    numloops = boundary_loops.numels();

    double adist, mindist = DBL_MAX;
    gv = NULL; gw = NULL;
    for (i = 0; i < numloops; i++)
        for (j = 0; j < numloops; j++)
            if (((Vertex *)bloops_array[i]->head()->data)->info
                != ((Vertex *)bloops_array[j]->head()->data)->info) {
                adist = closestPair(bloops_array[i], bloops_array[j], &v, &w);
                if (adist < mindist) { mindist = adist; gv = v; gw = w; }
            }

    if (gv != NULL) tin->joinBoundaryLoops(gv, gw, 1, 0);

    FOREACHVTTRIANGLE((&(tin->T)), t, n) t->info = NULL;
    FOREACHVVVERTEX((&(tin->V)), v, n) v->info = NULL;

    free(bloops_array);
    while ((one_loop = (List *)boundary_loops.popHead()) != NULL) delete one_loop;

    return (gv != NULL);
}

void report(char *error, int32_t capacity, const char *text) {
    if (error == NULL || capacity <= 0) return;
    strncpy(error, text, (size_t)capacity - 1);
    error[capacity - 1] = '\0';
}

}  // namespace

extern "C" {

int meshfix_repair(const double *vertices, int32_t vertex_count,
                   const int32_t *faces, int32_t face_count,
                   int join_components,
                   MFMesh *out,
                   char *error, int32_t error_capacity) {
    if (out == NULL) return MF_BAD_INPUT;
    memset(out, 0, sizeof(*out));
    if (vertices == NULL || faces == NULL || vertex_count < 3 || face_count < 1) {
        report(error, error_capacity, "no usable geometry supplied");
        return MF_BAD_INPUT;
    }

    TMesh::quiet = true;
    TMesh::display_message = messageHook;

    try {
        ArrayMesh tin;
        if (!tin.build(vertices, vertex_count, faces, face_count)) {
            report(error, error_capacity, "no valid triangles could be built");
            return MF_BAD_INPUT;
        }

        // The sequence MeshFix's own CLI runs, in the same order.
        if (join_components) {
            while (joinClosestComponents(&tin)) { /* until one shell remains */ }
            tin.deselectTriangles();
        } else {
            tin.removeSmallestComponents();
        }

        if (tin.boundaries()) tin.fillSmallBoundaries(0, true);
        tin.meshclean();

        if (!tin.extract(out)) {
            report(error, error_capacity, "repair produced an empty mesh");
            return MF_EMPTY_RESULT;
        }
        return MF_OK;

    } catch (const MeshFixAbort &e) {
        report(error, error_capacity, e.what());
        memset(out, 0, sizeof(*out));
        return MF_FAILED;
    } catch (const std::exception &e) {
        report(error, error_capacity, e.what());
        memset(out, 0, sizeof(*out));
        return MF_FAILED;
    } catch (...) {
        report(error, error_capacity, "MeshFix failed with an unknown error");
        memset(out, 0, sizeof(*out));
        return MF_FAILED;
    }
}

void meshfix_free(MFMesh *mesh) {
    if (mesh == NULL) return;
    free(mesh->vertices);
    free(mesh->faces);
    memset(mesh, 0, sizeof(*mesh));
}

const char *meshfix_version(void) { return "MeshFix 2.1"; }

}  // extern "C"
