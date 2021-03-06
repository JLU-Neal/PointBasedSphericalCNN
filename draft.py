import time

import numpy as np
import matplotlib as mpl

mpl.use('TkAgg')
import matplotlib.pyplot as plt
# import healpy as hp
# import trimesh
from mpl_toolkits.mplot3d import Axes3D
from sklearn.linear_model import LinearRegression





bandwidth =16

def load_obj(path):
    #import os
    #import numpy as np
    with open(path) as file:
        points = []
        while 1:
            line = file.readline()
            if not line:
                break
            strs = line.split(" ")
            if strs[0] == "v":
                points.append((float(strs[1]), float(strs[2]), float(strs[3])))
            if strs[0] == "vt":
                break
    # points原本为列表，需要转变为矩阵，方便处理
    points = np.array(points)
    return points

# from lie_learn.spaces import S2

def rotmat(a, b, c, hom_coord=False):  # apply to mesh using mesh.apply_transform(rotmat(a,b,c, True))
    """
    Create a rotation matrix with an optional fourth homogeneous coordinate

    :param a, b, c: ZYZ-Euler angles
    """

    def z(a):
        return np.array([[np.cos(a), np.sin(a), 0, 0],
                         [-np.sin(a), np.cos(a), 0, 0],
                         [0, 0, 1, 0],
                         [0, 0, 0, 1]])

    def y(a):
        return np.array([[np.cos(a), 0, np.sin(a), 0],
                         [0, 1, 0, 0],
                         [-np.sin(a), 0, np.cos(a), 0],
                         [0, 0, 0, 1]])

    r = z(a).dot(y(b)).dot(z(c))  # pylint: disable=E1101
    if hom_coord:
        return r
    else:
        return r[:3, :3]


def make_sgrid(b, alpha, beta, gamma):
    from lie_learn.spaces import S2

    beta, alpha = S2.meshgrid(b=b, grid_type='SOFT')

    sgrid = S2.change_coordinates(np.c_[beta[..., None], alpha[..., None]], p_from='S', p_to='C')

    # sgrid = sgrid.reshape((-1, 3))

    # R = rotmat(alpha, beta, gamma, hom_coord=False)
    # sgrid = np.einsum('ij,nj->ni', R, sgrid)#rotation

    return sgrid


def s2_equatorial_grid(max_beta=0, n_alpha=32, n_beta=1):
    '''
    :return: rings around the equator
    size of the kernel = n_alpha * n_beta
    '''
    beta = np.linspace(start=np.pi / 2 - max_beta, stop=np.pi / 2 + max_beta, num=n_beta, endpoint=True)
    alpha = np.linspace(start=0, stop=2 * np.pi, num=n_alpha, endpoint=False)
    B, A = np.meshgrid(beta, alpha, indexing='ij')
    B = B.flatten()
    A = A.flatten()
    grid = np.stack((B, A), axis=1)
    return tuple(tuple(ba) for ba in grid)


def linear_regression(northwest: np.ndarray=None, north:np.ndarray=None, northeast:np.ndarray=None,
                      west:np.ndarray=None, center:np.ndarray=None, east:np.ndarray=None,
                      southwest:np.ndarray=None, south:np.ndarray=None, southeast:np.ndarray=None):
    lr = LinearRegression(copy_X=True, fit_intercept=True, n_jobs=1, normalize=False)
    coef = np.array([]).reshape(-1, 2)
    intercept = np.array([]).reshape(-1, 1)
    for index in range(center.shape[0]):
        points=center[index]
        if northwest is not None:
            points=np.vstack((points,northwest[index]))
        if north is not None:
            points=np.vstack((points,north[index]))
        if northeast is not None:
            points=np.vstack((points,northeast[index]))
        if west is not None:
            points=np.vstack((points,west[index]))
        if east is not None:
            points=np.vstack((points,east[index]))
        if southwest is not None:
            points = np.vstack((points, southwest[index]))
        if south is not None:
            points = np.vstack((points, south[index]))
        if southeast is not None:
            points = np.vstack((points, southeast[index]))

        #points = np.stack((northwest[index], north[index], northeast[index], west[index], center[index], east[index], southwest[index], south[index], southeast[index]), axis=0)
        X = points[:, 0:2]
        Y = points[:, 2]
        reg = lr.fit(X, Y)
        # coef = reg.coef_
        coef = np.vstack((coef, reg.coef_))
        # intercept = reg.intercept_
        intercept = np.vstack((intercept, reg.intercept_))
    return coef, intercept


def interpolate(m: np.ndarray, n: np.ndarray, sgrid: np.ndarray, points_on_sphere: np.ndarray, radius: np.ndarray):
    print("Interpolate")
    m = m.copy()
    n = n.copy()
    sgrid = sgrid.copy()
    points_on_sphere = points_on_sphere.copy()
    radius = radius.copy()

    # Initialize the variables
    center_grid = np.zeros((m.shape[0],3))
    east_grid = np.zeros((m.shape[0],3))
    south_grid = np.zeros((m.shape[0],3))
    southeast_grid = np.zeros((m.shape[0],3))

    center_dist = np.zeros(m.shape[0])
    east_dist = np.zeros(m.shape[0])
    south_dist = np.zeros(m.shape[0])
    southeast_dist = np.zeros(m.shape[0])

    center_weight = np.zeros(m.shape[0])
    east_weight = np.zeros(m.shape[0])
    south_weight = np.zeros(m.shape[0])
    southeast_weight = np.zeros(m.shape[0])

    # use a mask to select the point on the  boundary============================
    mask_north = m == 0
    mask_south = m == sgrid.shape[0] - 1
    mask_boundary = mask_north + mask_south
    m_boundary = m[mask_boundary]
    n_boundary = n[mask_boundary] % sgrid.shape[1]
    n_boundary_plus_one = (n_boundary + 1) % sgrid.shape[1]
    n_boundary_opposite = (n_boundary + (sgrid.shape[1] / 2)) % sgrid.shape[1]
    n_boundary_opposite=n_boundary_opposite.astype(int)
    n_boundary_plus_one_opposite = (n_boundary_plus_one + (sgrid.shape[1] / 2))%sgrid.shape[1]
    n_boundary_plus_one_opposite=n_boundary_plus_one_opposite.astype(int)
    center_grid[mask_boundary] = sgrid[m_boundary, n_boundary]
    east_grid[mask_boundary] = sgrid[m_boundary, n_boundary_plus_one]
    south_grid[mask_boundary] = sgrid[m_boundary, n_boundary_opposite]
    southeast_grid[mask_boundary] = sgrid[m_boundary, n_boundary_plus_one_opposite]

    # calculate distance and relevant weight
    center_dist[mask_boundary] = np.sqrt(np.sum((center_grid[mask_boundary] - points_on_sphere[mask_boundary]) ** 2))
    east_dist[mask_boundary] = np.sqrt(np.sum((east_grid[mask_boundary] - points_on_sphere[mask_boundary]) ** 2))
    south_dist[mask_boundary] = np.sqrt(np.sum((south_grid[mask_boundary] - points_on_sphere[mask_boundary]) ** 2))
    southeast_dist[mask_boundary] = np.sqrt(
        np.sum((southeast_grid[mask_boundary] - points_on_sphere[mask_boundary]) ** 2))
    sum = center_dist[mask_boundary] + east_dist[mask_boundary] + south_dist[mask_boundary] + southeast_dist[
        mask_boundary]
    center_weight[mask_boundary] = center_dist[mask_boundary] / sum
    east_weight[mask_boundary] = east_dist[mask_boundary] / sum
    south_weight[mask_boundary] = south_dist[mask_boundary] / sum
    southeast_weight[mask_boundary] = southeast_dist[mask_boundary] / sum

    # save the signal of distance
    radius_boundary = radius[mask_boundary]
    dist_im = np.zeros(sgrid.shape[0:2])  # signal of distance from points to sphere
    weight_im = np.zeros(sgrid.shape[
                         0:2])  # Since each grid point on the sphere could be affected by several different signals, we need to normalize the values.
    dist_im[m_boundary, n_boundary] += radius_boundary[:, 0] * center_weight[mask_boundary]
    dist_im[m_boundary, n_boundary_plus_one] += radius_boundary[:, 0] * east_weight[mask_boundary]
    dist_im[m_boundary, n_boundary_opposite] += radius_boundary[:, 0] * south_weight[mask_boundary]
    dist_im[m_boundary, n_boundary_plus_one_opposite] += radius_boundary[:, 0] * southeast_weight[mask_boundary]
    weight_im[m_boundary, n_boundary] += center_weight[mask_boundary]
    weight_im[m_boundary, n_boundary_plus_one] += east_weight[mask_boundary]
    weight_im[m_boundary, n_boundary_opposite] += south_weight[mask_boundary]
    weight_im[m_boundary, n_boundary_plus_one_opposite] += southeast_weight[mask_boundary]

    # use a mask to select the rest points===============================
    mask_rest = ~mask_boundary
    m_rest = m[mask_rest]
    n_rest = n[mask_rest] % sgrid.shape[1]
    n_rest_plus_one = (n_rest + 1) % sgrid.shape[1]
    center_grid[mask_rest] = sgrid[m_rest, n_rest]
    east_grid[mask_rest] = sgrid[m_rest, n_rest_plus_one]
    south_grid[mask_rest] = sgrid[m_rest + 1, n_rest]
    southeast_grid[mask_rest] = sgrid[m_rest + 1, n_rest_plus_one]

    # calculate distance and relevant weight
    center_dist[mask_rest] = np.sqrt(np.sum((center_grid[mask_rest] - points_on_sphere[mask_rest]) ** 2))
    east_dist[mask_rest] = np.sqrt(np.sum((east_grid[mask_rest] - points_on_sphere[mask_rest]) ** 2))
    south_dist[mask_rest] = np.sqrt(np.sum((south_grid[mask_rest] - points_on_sphere[mask_rest]) ** 2))
    southeast_dist[mask_rest] = np.sqrt(np.sum((southeast_grid[mask_rest] - points_on_sphere[mask_rest]) ** 2))
    sum = center_dist[mask_rest] + east_dist[mask_rest] + south_dist[mask_rest] + southeast_dist[mask_rest]
    center_weight[mask_rest] = center_dist[mask_rest] / sum
    east_weight[mask_rest] = east_dist[mask_rest] / sum
    south_weight[mask_rest] = south_dist[mask_rest] / sum
    southeast_weight[mask_rest] = southeast_dist[mask_rest] / sum

    # save the signal of distance
    radius_rest = radius[mask_rest]
    dist_im = np.zeros(sgrid.shape[0:2])  # signal of distance from points to sphere
    weight_im = np.zeros(sgrid.shape[
                         0:2])  # Since each grid point on the sphere could be affected by several different signals, we need to normalize the values.
    dist_im[m_rest, n_rest] += radius_rest[:, 0] * center_weight[mask_rest]
    dist_im[m_rest, n_rest_plus_one] += radius_rest[:, 0] * east_weight[mask_rest]
    dist_im[m_rest + 1, n_rest] += radius_rest[:, 0] * south_weight[mask_rest]
    dist_im[m_rest + 1, n_rest_plus_one] += radius_rest[:, 0] * southeast_weight[mask_rest]
    weight_im[m_rest, n_rest] += center_weight[mask_rest]
    weight_im[m_rest, n_rest_plus_one] += east_weight[mask_rest]
    weight_im[m_rest + 1, n_rest] += south_weight[mask_rest]
    weight_im[m_rest + 1, n_rest_plus_one] += southeast_weight[mask_rest]

    mask_weight = weight_im != 0
    dist_im[mask_weight] /= weight_im[mask_weight]
    dist_im = 1 - dist_im
    return dist_im, center_grid, east_grid, south_grid, southeast_grid

def angle(m:np.ndarray,n:np.ndarray,sgrid:np.ndarray,dist_im:np.ndarray):
    print("angle")
    m=m.copy()
    n=n.copy()
    n=n%sgrid.shape[1]
    sgrid=sgrid.copy()
    dist_im=dist_im.copy()
    # utilizing linear regression to create a plane

    # use a mask to avoid the index out of the boundary
    """
    mask_m = m - 1 >= 0
    mask = mask_m
    m = m[mask]
    n = n[mask]
    """
    #Initialize the variables
    northwest_points = np.zeros((m.shape[0],3))
    north_points = np.zeros((m.shape[0],3))
    northeast_points = np.zeros((m.shape[0],3))
    west_points = np.zeros((m.shape[0],3))
    center_points = np.zeros((m.shape[0],3))
    east_points = np.zeros((m.shape[0],3))
    southwest_points = np.zeros((m.shape[0],3))
    south_points = np.zeros((m.shape[0],3))
    southeast_points = np.zeros((m.shape[0],3))
    coef=np.zeros((m.shape[0],2))
    intercept=np.zeros((m.shape[0],1))


    #calculate the coef & intercept of points on the north boundary
    mask_north = m == 0
    m_north = m[mask_north]
    if m_north.size != 0:
        n_north = n[mask_north] % sgrid.shape[1]
        n_north_minus_one=(n_north-1)%sgrid.shape[1]
        n_north_plus_one=(n_north+1)%sgrid.shape[1]
        west_points[mask_north] = sgrid[m_north, n_north_minus_one] * (1 - np.repeat(dist_im[m_north, n_north_minus_one], 3).reshape(-1, 3))
        center_points[mask_north] = sgrid[m_north, n_north] * (1 - np.repeat(dist_im[m_north, n_north], 3).reshape(-1, 3))
        east_points[mask_north] = sgrid[m_north, n_north_plus_one] * (1 - np.repeat(dist_im[m_north, n_north_plus_one], 3).reshape(-1, 3))
        southwest_points[mask_north] = sgrid[m_north + 1, n_north_minus_one] * (1 - np.repeat(dist_im[m_north + 1, n_north_minus_one], 3).reshape(-1, 3))
        south_points[mask_north] = sgrid[m_north + 1, n_north] * (1 - np.repeat(dist_im[m_north + 1, n_north], 3).reshape(-1, 3))
        southeast_points[mask_north] = sgrid[m_north + 1, n_north_plus_one] * (1 - np.repeat(dist_im[m_north + 1, n_north_plus_one], 3).reshape(-1, 3))
        coef[mask_north,:], intercept[mask_north] = linear_regression(northwest=None, north=None, northeast=None,
                                                                    west=west_points[mask_north], center=center_points[mask_north], east=east_points[mask_north],
                                                                    southwest=southwest_points[mask_north], south=south_points[mask_north], southeast=southeast_points[mask_north])

    # calculate the coef & intercept of points on the south boundary
    mask_south = m == sgrid.shape[0] - 1
    m_south = m[mask_south]
    if m_south.size !=0:
        n_south = n[mask_south] % sgrid.shape[1]
        n_south_minus_one = (n_south - 1) % sgrid.shape[1]
        n_south_plus_one = (n_south + 1) % sgrid.shape[1]
        northwest_points[mask_south] = sgrid[m_south - 1, n_south_minus_one] * (1 - np.repeat(dist_im[m_south - 1, n_south_minus_one], 3).reshape(-1, 3))
        north_points[mask_south] = sgrid[m_south - 1, n_south] * (1 - np.repeat(dist_im[m_south - 1, n_south], 3).reshape(-1, 3))
        northeast_points[mask_south] = sgrid[m_south - 1, n_south_plus_one] * (1 - np.repeat(dist_im[m_south - 1, n_south_plus_one], 3).reshape(-1, 3))
        west_points[mask_south] = sgrid[m_south, n_south_minus_one] * (1 - np.repeat(dist_im[m_south, n_south_minus_one], 3).reshape(-1, 3))
        center_points[mask_south] = sgrid[m_south, n_south] * (1 - np.repeat(dist_im[m_south, n_south], 3).reshape(-1, 3))
        east_points[mask_south] = sgrid[m_south, n_south_plus_one] * (1 - np.repeat(dist_im[m_south, n_south_plus_one], 3).reshape(-1, 3))

        coef[mask_south,:], intercept[mask_south] = linear_regression(northwest=northwest_points[mask_south], north=north_points[mask_south], northeast=northeast_points[mask_south],
                                                                    west=west_points[mask_south], center=center_points[mask_south], east=east_points[mask_south],
                                                                    southwest=None, south=None, southeast=None)

    #calculate the rest points
    mask_boundary=mask_north+mask_south
    mask_rest=~mask_boundary
    m_rest=m[mask_rest]
    n_rest=n[mask_rest]%sgrid.shape[1]
    n_rest_minus_one = (n_rest - 1) % sgrid.shape[1]
    n_rest_plus_one = (n_rest + 1) % sgrid.shape[1]

    # calculate the estimated position of the points corresponded to the grids
    northwest_points[mask_rest] = sgrid[m_rest - 1, n_rest_minus_one] * (1 - np.repeat(dist_im[m_rest - 1, n_rest_minus_one], 3).reshape(-1, 3))
    north_points[mask_rest] = sgrid[m_rest - 1, n_rest] * (1 - np.repeat(dist_im[m_rest - 1, n_rest], 3).reshape(-1, 3))
    northeast_points[mask_rest] = sgrid[m_rest - 1, n_rest_plus_one] * (1 - np.repeat(dist_im[m_rest - 1, n_rest_plus_one], 3).reshape(-1, 3))
    west_points[mask_rest] = sgrid[m_rest, n_rest_minus_one] * (1 - np.repeat(dist_im[m_rest, n_rest_minus_one], 3).reshape(-1, 3))
    center_points[mask_rest] = sgrid[m_rest, n_rest] * (1 - np.repeat(dist_im[m_rest, n_rest], 3).reshape(-1, 3))
    east_points[mask_rest] = sgrid[m_rest, n_rest_plus_one] * (1 - np.repeat(dist_im[m_rest, n_rest_plus_one], 3).reshape(-1, 3))
    southwest_points[mask_rest] = sgrid[m_rest + 1, n_rest_minus_one] * (1 - np.repeat(dist_im[m_rest + 1, n_rest_minus_one], 3).reshape(-1, 3))
    south_points[mask_rest] = sgrid[m_rest + 1, n_rest] * (1 - np.repeat(dist_im[m_rest + 1, n_rest], 3).reshape(-1, 3))
    southeast_points[mask_rest] = sgrid[m_rest + 1, n_rest_plus_one] * (1 - np.repeat(dist_im[m_rest + 1, n_rest_plus_one], 3).reshape(-1, 3))
    coef[mask_rest,:], intercept[mask_rest] = linear_regression(northwest=northwest_points[mask_rest], north=north_points[mask_rest], northeast=northeast_points[mask_rest],
                                                                west=west_points[mask_rest], center=center_points[mask_rest], east=east_points[mask_rest],
                                                                southwest=southwest_points[mask_rest], south=south_points[mask_rest], southeast=southeast_points[mask_rest])
    #calculate the angle signals
    dot_im = np.zeros(sgrid.shape[0:2])  # signal of dot production between rays and normals
    cross_im=dist_im = np.zeros(sgrid.shape[0:2])  # signal of cross production between rays and normals
    normals=np.zeros((m.shape[0],3))
    normals[:,0:2] = coef
    normals[:,2] = -1
    normalized_normals = normals / np.linalg.norm(normals, axis=1, keepdims=True)
    dot_im[m,n]=np.abs(np.einsum("ij,ij->i", normalized_normals, sgrid[m,n]))
    nx, ny, nz = normalized_normals[:, 0], normalized_normals[:, 1], normalized_normals[:, 2]
    cx, cy, cz = center_points[:, 0], center_points[:, 1], center_points[:, 2]
    cross_im[m,n]=np.sqrt((nx * cy - ny * cx) ** 2 + (nx * cz - nz * cx) ** 2 + (ny * cz - nz * cy) ** 2)
    return coef, intercept,center_points

def inverse_render_model(points: np.ndarray, sgrid: np.ndarray):
    # wait for implementing
    print("Aloha")

    x = points[:, 0]
    y = points[:, 1]
    z = points[:, 2]
    # Fistly, we get the centroid, then translate the points
    centroid_x = np.sum(x) / points.shape[0]
    centroid_y = np.sum(y) / points.shape[0]
    centroid_z = np.sum(z) / points.shape[0]
    centroid = np.array([centroid_x, centroid_y, centroid_z])
    points = points.astype(np.float)
    points -= centroid

    # After normalization, compute the distance between the sphere and points

    radius = np.sqrt(points[:, 0] ** 2 + points[:, 1] ** 2 + points[:, 2] ** 2)
    # dist = 1 - (1 / np.max(radius)) * radius

    # Projection
    from lie_learn.spaces import S2
    radius = np.repeat(radius, 3).reshape(-1, 3)
    points_on_sphere = points / radius
    # ssgrid = sgrid.reshape(-1, 3)
    # phi, theta = S2.change_coordinates(ssgrid, p_from='C', p_to='S')
    out = S2.change_coordinates(points_on_sphere, p_from='C', p_to='S')

    phi = out[..., 0]
    theta = out[..., 1]

    phi = phi
    theta = theta % (np.pi * 2)

    # Interpolate
    b = sgrid.shape[0] / 2  # bandwidth
    # By computing the m,n, we can find
    # the neighbours on the sphere
    m = np.trunc((phi - np.pi / (4 * b)) / (np.pi / (2 * b)))
    m = m.astype(int)
    n = np.trunc(theta / (np.pi / b))
    n = n.astype(int)

    dist_im, center_grid, east_grid, south_grid, southeast_grid = interpolate(m=m, n=n, sgrid=sgrid,
                                                                              points_on_sphere=points_on_sphere,
                                                                              radius=radius)
    coef, intercept,center_points =angle(m=m,n=n,sgrid=sgrid,dist_im=dist_im)
    # utilizing linear regression to create a plane

    # use a mask to avoid the index out of the boundary
    """
    mask_m = m - 1 >= 0
    mask = mask_m
    m = m[mask]
    n = n[mask]
    """

    # =======================================================================================
    fig = plt.figure()
    grid = make_sgrid(bandwidth, 0, 0, 0)
    grid = grid.reshape((-1, 3))

    xx = grid[:, 0]
    yy = grid[:, 1]
    zz = grid[:, 2]
    xx = xx.reshape(-1, 1)
    yy = yy.reshape(-1, 1)
    zz = zz.reshape(-1, 1)
    ax = Axes3D(fig)
    ax.scatter(0, 0, 0)

    ax.scatter(points[:, 0], points[:, 1], points[:, 2])
    ax.scatter(points_on_sphere[:, 0], points_on_sphere[:, 1], points_on_sphere[:, 2])

    ax.scatter(center_grid[:, 0], center_grid[:, 1], center_grid[:, 2])
    ax.scatter(east_grid[:, 0], east_grid[:, 1], east_grid[:, 2])
    ax.scatter(south_grid[:, 0], south_grid[:, 1], south_grid[:, 2])
    ax.scatter(southeast_grid[:, 0], southeast_grid[:, 1], southeast_grid[:, 2])
    # ax.scatter(xx, yy, zz)
    # plt.legend()

    # draw line
    ax = fig.gca(projection='3d')
    zero = np.zeros(points_on_sphere.shape[0])
    ray_x = np.stack((zero, points_on_sphere[:, 0]), axis=1).reshape(-1, 2)
    ray_y = np.stack((zero, points_on_sphere[:, 1]), axis=1).reshape(-1, 2)
    ray_z = np.stack((zero, points_on_sphere[:, 2]), axis=1).reshape(-1, 2)
    for index in range(points_on_sphere.shape[0]):
        ax.plot(ray_x[index], ray_y[index], ray_z[index])

    # draw plane
    for index in range(center_points.shape[0]):
        X = np.arange(center_points[index, 0] - 0.05, center_points[index, 0] + 0.05, 0.01)
        Y = np.arange(center_points[index, 1] - 0.05, center_points[index, 1] + 0.05, 0.01)
        X, Y = np.meshgrid(X, Y)
        a1 = coef[index, 0]
        a2 = coef[index, 1]
        b = intercept[index]
        Z = a1 * X + a2 * Y + b
        surf = ax.plot_surface(X, Y, Z)

    plt.show()
    im = dist_im
    return im




class ToPoints:
    def __init__(self, random_rotation=False, random_translation=0):
        self.rot = random_rotation
        self.tr = random_translation

    def __call__(self, path):
        print("HOLA")
        # mesh=trimesh.load_mesh(path)


class ProjectFromPointsOnSphere:
    # Wait for implementing
    def __init__(self, bandwidth):
        self.bandwidth = bandwidth
        self.sgrid = make_sgrid(bandwidth, alpha=0, beta=0, gamma=0)  # create a sphere grid
        print("Aloha")

    def __call__(self, points):
        im = inverse_render_model(points, self.sgrid)
        im = im.astype(np.float32)
        return im

    def __repr__(self):
        return self.__class__.__name__ + '(bandwidth={0})'.format(self.bandwidth)





pfpos = ProjectFromPointsOnSphere(bandwidth)
#a = np.array([[0, 0, -1], [0, 0, 1]]).reshape(-1, 3)
#a = np.random.random((250, 3))
a=make_sgrid(bandwidth,0,0,0).reshape(-1,3)
a = a * 0.5
im = pfpos(a)
