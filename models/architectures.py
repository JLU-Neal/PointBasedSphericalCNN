#
#
#      0=================================0
#      |    Kernel Point Convolutions    |
#      0=================================0
#
#
# ----------------------------------------------------------------------------------------------------------------------
#
#      Define network architectures
#
# ----------------------------------------------------------------------------------------------------------------------
#
#      Hugues THOMAS - 06/03/2020
#

from models.blocks import *
import numpy as np
from models.spherical_model import SphericalCNN
from models.shared_mlp import SharedMLP
from models.pointnet import PointNetEncoder
import torch.nn.functional as F
import warnings
import torch.nn as nn

def p2p_fitting_regularizer(net):
    fitting_loss = 0
    repulsive_loss = 0

    for m in net.modules():

        if isinstance(m, KPConv) and m.deformable:

            ##############
            # Fitting loss
            ##############

            # Get the distance to closest input point and normalize to be independant from layers
            KP_min_d2 = m.min_d2 / (m.KP_extent ** 2)

            # Loss will be the square distance to closest input point. We use L1 because dist is already squared
            fitting_loss += net.l1(KP_min_d2, torch.zeros_like(KP_min_d2))

            ################
            # Repulsive loss
            ################

            # Normalized KP locations
            KP_locs = m.deformed_KP / m.KP_extent

            # Point should not be close to each other
            for i in range(net.K):
                other_KP = torch.cat([KP_locs[:, :i, :], KP_locs[:, i + 1:, :]], dim=1).detach()
                distances = torch.sqrt(torch.sum((other_KP - KP_locs[:, i:i + 1, :]) ** 2, dim=2))
                rep_loss = torch.sum(torch.clamp_max(distances - net.repulse_extent, max=0.0) ** 2, dim=1)
                repulsive_loss += net.l1(rep_loss, torch.zeros_like(rep_loss)) / net.K

    return net.deform_fitting_power * (2 * fitting_loss + repulsive_loss)

class div(nn.Module):

    def __init__(self):
        """
        Initialize a standard unary block with its ReLU and BatchNorm.
        :param in_dim: dimension input features
        :param out_dim: dimension input features
        :param use_bn: boolean indicating if we use Batch Norm
        :param bn_momentum: Batch norm momentum
        """
        super(div, self).__init__()



    def forward(self,features):
        temp = torch.zeros(features.shape)
        for index in range(features.shape[0]):
            norm = torch.norm(features[index], float('inf'))
            temp[index] = torch.div(features[index], norm)

        return temp.cuda()

class KPCNN(nn.Module):
    """
    Class defining KPCNN
    """

    def __init__(self, config):
        super(KPCNN, self).__init__()

        #####################
        # Network opperations
        #####################

        # Current radius of convolution and feature dimension
        layer = 0
        r = config.first_subsampling_dl * config.conv_radius
        in_dim = config.in_features_dim
        out_dim = config.first_features_dim
        self.K = config.num_kernel_points

        # Save all block operations in a list of modules
        self.block_ops = nn.ModuleList()

        # Loop over consecutive blocks
        block_in_layer = 0
        for block_i, block in enumerate(config.architecture):

            # Check equivariance
            if ('equivariant' in block) and (not out_dim % 3 == 0):
                raise ValueError('Equivariant block but features dimension is not a factor of 3')

            # Detect upsampling block to stop
            if 'upsample' in block:
                break

            # Apply the good block function defining tf ops
            self.block_ops.append(block_decider(block,
                                                r,
                                                in_dim,
                                                out_dim,
                                                layer,
                                                config))

            # Index of block in this layer
            block_in_layer += 1

            # Update dimension of input from output
            if 'simple' in block:
                in_dim = out_dim // 2
            else:
                in_dim = out_dim

            # Detect change to a subsampled layer
            if 'pool' in block or 'strided' in block:
                # Update radius and feature dimension for next layer
                layer += 1
                r *= 2
                out_dim *= 2
                block_in_layer = 0

        # self.head_mlp = UnaryBlock(out_dim + 512, 512, False, 0)
        # self.bn = torch.nn.BatchNorm1d(1024)
        # self.head_mlp1 = UnaryBlock(512, 128, False, 0)
        # self.head_mlp2 = UnaryBlock(128, 64, False, 0)
        # self.head_softmax = UnaryBlock(64, config.num_classes, False, 0)
        self.point_net_out = 128
        self.sphere_out = 128
        self.all_dropout_ratio = 0

        self.head_mlp = UnaryBlock(out_dim, 1024, False, 0)
        if self.all_dropout_ratio != 0:
            self.x_dropout = nn.Dropout(p=self.all_dropout_ratio)
            print("Point based convolution models use dropout.")
        else:
            self.x_dropout = None
        self.x_div = div()
        self.head_softmax = UnaryBlock(#1024 +
                                        self.sphere_out
                                       #+ self.point_net_out
                                       , config.num_classes, False, 0)
        ################
        # Network Losses
        ################

        self.criterion = torch.nn.CrossEntropyLoss()
        self.deform_fitting_mode = config.deform_fitting_mode
        self.deform_fitting_power = config.deform_fitting_power
        self.deform_lr_factor = config.deform_lr_factor
        self.repulse_extent = config.repulse_extent
        self.output_loss = 0
        self.reg_loss = 0
        self.l1 = nn.L1Loss()
        self.spherical_features = SphericalCNN(out_channels=1024, dropout_ratio=self.all_dropout_ratio)
        self.spherical_mlp = UnaryBlock(1024, self.sphere_out, False, 0)
        self.spherical_insNorm = nn.InstanceNorm1d(self.sphere_out)
        self.spherical_div = div()
        # self.point_features = SharedMLP(in_channels=3, out_channels=[64, 128, 32])
        # self.point_mlp = UnaryBlock(1024, 128, False, 0)
        # self.point_bn = nn.BatchNorm1d(128)
        # self.fusion = SharedMLP(in_channels=256, out_channels=[1024])
        self.point_net = PointNetEncoder(output_channel=1024)
        #self.point_net_insNorm = nn.InstanceNorm1d(self.point_net_out)
        self.point_net_div = div()
        self.fc1 = nn.Linear(1024, 512)
        self.fc2 = nn.Linear(512, 256)
        self.fc3 = nn.Linear(256, self.point_net_out)
        self.dropout = nn.Dropout(p=0.4)
        self.bn1 = nn.BatchNorm1d(512)
        self.bn2 = nn.BatchNorm1d(256)
        self.relu = nn.ReLU()
        return


    def forward(self, batch, config):
        # Get input features
        transformed_data = batch.transformed_data
        points_data = batch.points[0]
        points_data = points_data.unsqueeze(0)
        points_data = points_data.transpose(2, 1)

        out_feature_list = []
        # Save all block operations in a list of modules
        x = batch.features.clone().detach()

        # Loop over consecutive blocks
        for block_op in self.block_ops:
            x = block_op(x, batch)
        # out_feature_list.append(x)
        # Head of network

        # points_num = x.shape[0]

        spherical_features = self.spherical_features(transformed_data)
        spherical_features = self.spherical_mlp(spherical_features)
        spherical_features = self.spherical_div(spherical_features)
        out_feature_list.append(spherical_features)

        # point_features = self.point_features(points_data, batch)  # need batch as parameter to split the points
        # point_features = [array.transpose(2, 1) for array in point_features]
        # point_features = [array[0, ...] for array in point_features]
        # point_features = [torch.max(array, 0, keepdim=True)[0] for array in point_features]
        # point_features = torch.cat(point_features, dim=0)



        point_features = self.point_net(points_data, batch)
        #point_features = torch.cat(point_features, dim=0)
        if point_features.shape[0] > 1:
            point_features = F.relu(self.bn1(self.fc1(point_features)))
            point_features = F.relu(self.bn2(self.dropout(self.fc2(point_features))))
            point_features = self.fc3(point_features)
        else:
            warnings.warn('Not using Batch Normalization since the batchsize is 1')
            point_features = F.relu(self.fc1(point_features))
            point_features = F.relu(self.dropout(self.fc2(point_features)))
            point_features = self.fc3(point_features)

        point_features = self.point_net_div(point_features)
        #out_feature_list.append(point_features)
        if self.x_dropout:
            x = self.head_mlp(self.x_dropout(x), batch)
        else:
            x = self.head_mlp(x, batch)
        x = self.x_div(x)
        #out_feature_list.append(x)
        out_feature = torch.cat(out_feature_list, dim=1)
        # = self.head_mlp1(out_feature, batch)
        # out_feature = self.head_mlp2(out_feature, batch)
        out_feature = self.head_softmax(out_feature, batch)
        """

        """

        """
        # Get input features
        transformed_data = batch.transformed_data
        points_data = batch.points[0]
        points_data = points_data.unsqueeze(0)
        points_data = points_data.transpose(2, 1)

        out_feature_list = []
        # Save all block operations in a list of modules
        x = batch.features.clone().detach()

        # Loop over consecutive blocks
        for block_op in self.block_ops:
            x = block_op(x, batch)
        
        # Head of network
        spherical_features = self.spherical_features(transformed_data)
        # spherical_features = spherical_features.repeat(points_num, 1)
        spherical_features = [spherical_features[index].unsqueeze(0) for index in range(len(spherical_features))]
        spherical_features = [spherical_features[index].repeat(batch.lengths[0][index], 1) for index in
                              range(len(spherical_features))]
        spherical_features = torch.cat(spherical_features, dim=0)
        out_feature_list.append(spherical_features)

        point_features = self.point_features(points_data, batch)
        point_features = [array.transpose(2, 1) for array in point_features]
        point_features = [array[0, ...] for array in point_features]
        point_features = torch.cat(point_features, dim=0)
        out_feature_list.append(point_features)

        x = self.head_mlp(x, batch)
        x_list = [x[index] for index in range(x.shape[0])]
        x_list = [x[index].unsqueeze(0) for index in range(len(x_list))]
        x_list = [x_list[index].repeat(batch.lengths[0][index], 1) for index in
                              range(len(x_list))]
        x = torch.cat(x_list, dim=0)
        out_feature_list.append(x)

        #out_feature = torch.cat(out_feature_list, dim=1)
        out_feature = out_feature_list[0]+out_feature_list[1]+out_feature_list[2]
        out_feature = out_feature.transpose(1,0)
        out_feature = out_feature.unsqueeze(0)
        # out_feature = self.bn(out_feature)

        out_feature = self.fusion(out_feature, batch)#return a list
        out_feature = [array.transpose(2, 1) for array in out_feature]
        out_feature = [array[0, ...] for array in out_feature]

        out_feature = [torch.max(array, 0, keepdim=True)[0][0] for array in out_feature]
        out_feature = [self.head_mlp1(array, batch) for array in out_feature]
        out_feature = [self.head_mlp2(array, batch) for array in out_feature]
        out_feature = [self.head_softmax(array, batch) for array in out_feature]
        out_feature = [array.unsqueeze(0) for array in out_feature]
        out_feature = torch.cat(out_feature, dim=0)       
        """

        return out_feature
        """
        # Save all block operations in a list of modules
        x = batch.features.clone().detach()

        # Loop over consecutive blocks
        for block_op in self.block_ops:
            x = block_op(x, batch)

        # Head of network
        x = self.head_mlp(x, batch)
        x = self.head_softmax(x, batch)

        return x

        """

    def loss(self, outputs, labels):
        """
        Runs the loss on outputs of the model
        :param outputs: logits
        :param labels: labels
        :return: loss
        """

        # Cross entropy loss
        self.output_loss = self.criterion(outputs, labels)

        # Regularization of deformable offsets
        if self.deform_fitting_mode == 'point2point':
            self.reg_loss = p2p_fitting_regularizer(self)
        elif self.deform_fitting_mode == 'point2plane':
            raise ValueError('point2plane fitting mode not implemented yet.')
        else:
            raise ValueError('Unknown fitting mode: ' + self.deform_fitting_mode)

        # Combined loss
        return self.output_loss + self.reg_loss

    @staticmethod
    def accuracy(outputs, labels):
        """
        Computes accuracy of the current batch
        :param outputs: logits predicted by the network
        :param labels: labels
        :return: accuracy value
        """

        predicted = torch.argmax(outputs.data, dim=1)
        total = labels.size(0)
        correct = (predicted == labels).sum().item()

        return correct / total


class KPFCNN(nn.Module):
    """
    Class defining KPFCNN
    """

    def __init__(self, config, lbl_values, ign_lbls):
        super(KPFCNN, self).__init__()

        ############
        # Parameters
        ############

        # Current radius of convolution and feature dimension
        layer = 0
        r = config.first_subsampling_dl * config.conv_radius
        in_dim = config.in_features_dim
        out_dim = config.first_features_dim
        self.K = config.num_kernel_points
        self.C = len(lbl_values) - len(ign_lbls)

        #####################
        # List Encoder blocks
        #####################

        # Save all block operations in a list of modules
        self.encoder_blocks = nn.ModuleList()
        self.encoder_skip_dims = []
        self.encoder_skips = []

        # Loop over consecutive blocks
        for block_i, block in enumerate(config.architecture):

            # Check equivariance
            if ('equivariant' in block) and (not out_dim % 3 == 0):
                raise ValueError('Equivariant block but features dimension is not a factor of 3')

            # Detect change to next layer for skip connection
            if np.any([tmp in block for tmp in ['pool', 'strided', 'upsample', 'global']]):
                self.encoder_skips.append(block_i)
                self.encoder_skip_dims.append(in_dim)

            # Detect upsampling block to stop
            if 'upsample' in block:
                break

            # Apply the good block function defining tf ops
            self.encoder_blocks.append(block_decider(block,
                                                     r,
                                                     in_dim,
                                                     out_dim,
                                                     layer,
                                                     config))

            # Update dimension of input from output
            if 'simple' in block:
                in_dim = out_dim // 2
            else:
                in_dim = out_dim

            # Detect change to a subsampled layer
            if 'pool' in block or 'strided' in block:
                # Update radius and feature dimension for next layer
                layer += 1
                r *= 2
                out_dim *= 2

        #####################
        # List Decoder blocks
        #####################

        # Save all block operations in a list of modules
        self.decoder_blocks = nn.ModuleList()
        self.decoder_concats = []

        # Find first upsampling block
        start_i = 0
        for block_i, block in enumerate(config.architecture):
            if 'upsample' in block:
                start_i = block_i
                break

        # Loop over consecutive blocks
        for block_i, block in enumerate(config.architecture[start_i:]):

            # Add dimension of skip connection concat
            if block_i > 0 and 'upsample' in config.architecture[start_i + block_i - 1]:
                in_dim += self.encoder_skip_dims[layer]
                self.decoder_concats.append(block_i)

            # Apply the good block function defining tf ops
            self.decoder_blocks.append(block_decider(block,
                                                     r,
                                                     in_dim,
                                                     out_dim,
                                                     layer,
                                                     config))

            # Update dimension of input from output
            in_dim = out_dim

            # Detect change to a subsampled layer
            if 'upsample' in block:
                # Update radius and feature dimension for next layer
                layer -= 1
                r *= 0.5
                out_dim = out_dim // 2

        self.head_mlp = UnaryBlock(out_dim * 2, config.first_features_dim, False, 0)
        self.head_mlp1 = UnaryBlock(config.first_features_dim, 128, False, 0)
        # self.head_mlp2 = UnaryBlock(128, 64, False, 0)
        self.head_softmax = UnaryBlock(128, self.C, False, 0)

        ################
        # Network Losses
        ################

        # List of valid labels (those not ignored in loss)
        self.valid_labels = np.sort([c for c in lbl_values if c not in ign_lbls])

        # Choose segmentation loss
        if len(config.class_w) > 0:
            class_w = torch.from_numpy(np.array(config.class_w, dtype=np.float32))
            self.criterion = torch.nn.CrossEntropyLoss(weight=class_w, ignore_index=-1)
        else:
            self.criterion = torch.nn.CrossEntropyLoss(ignore_index=-1)
        self.deform_fitting_mode = config.deform_fitting_mode
        self.deform_fitting_power = config.deform_fitting_power
        self.deform_lr_factor = config.deform_lr_factor
        self.repulse_extent = config.repulse_extent
        self.output_loss = 0
        self.reg_loss = 0
        self.l1 = nn.L1Loss()
        self.spherical_features = SphericalCNN(out_channels=out_dim // 2)
        self.point_features = SharedMLP(in_channels=3, out_channels=[32, 64, out_dim // 2])
        # self.loss = self.loss
        return

    def forward(self, batch, config):

        # Get input features
        transformed_data = batch.transformed_data
        points_data = batch.points[0]
        points_data = points_data.unsqueeze(0)
        points_data = points_data.transpose(2, 1)
        x = batch.features.clone().detach()

        # Loop over consecutive blocks
        skip_x = []
        for block_i, block_op in enumerate(self.encoder_blocks):
            if block_i in self.encoder_skips:
                skip_x.append(x)
            x = block_op(x, batch)

        for block_i, block_op in enumerate(self.decoder_blocks):
            if block_i in self.decoder_concats:
                x = torch.cat([x, skip_x.pop()], dim=1)
            x = block_op(x, batch)

        # Head of network
        out_feature_list = []
        # points_num = points_data.shape[2]
        spherical_features = self.spherical_features(transformed_data)
        # spherical_features = spherical_features.repeat(points_num, 1)
        spherical_features = [spherical_features[index].unsqueeze(0) for index in range(len(spherical_features))]
        spherical_features = [spherical_features[index].repeat(batch.lengths[0][index], 1) for index in
                              range(len(spherical_features))]
        spherical_features = torch.cat(spherical_features, dim=0)
        out_feature_list.append(spherical_features)

        point_features = self.point_features(points_data, batch)
        point_features = [array.transpose(2, 1) for array in point_features]
        point_features = [array[0, ...] for array in point_features]
        point_features = torch.cat(point_features, dim=0)
        out_feature_list.append(point_features)

        # x = self.head_mlp(x, batch)
        out_feature_list.append(x)

        out_feature = torch.cat(out_feature_list, dim=1)
        out_feature = self.head_mlp(out_feature, batch)
        out_feature = self.head_mlp1(out_feature, batch)
        # out_feature = self.head_mlp2(out_feature, batch)
        out_feature = self.head_softmax(out_feature, batch)

        return out_feature

    def loss(self, outputs, labels):
        """
        Runs the loss on outputs of the model
        :param outputs: logits
        :param labels: labels
        :return: loss
        """

        # Set all ignored labels to -1 and correct the other label to be in [0, C-1] range
        target = - torch.ones_like(labels)
        for i, c in enumerate(self.valid_labels):
            target[labels == c] = i

        # Reshape to have a minibatch size of 1
        outputs = torch.transpose(outputs, 0, 1)
        outputs = outputs.unsqueeze(0)
        target = target.unsqueeze(0)

        # Cross entropy loss
        self.output_loss = self.criterion(outputs, target)

        # Regularization of deformable offsets
        if self.deform_fitting_mode == 'point2point':
            self.reg_loss = p2p_fitting_regularizer(self)
        elif self.deform_fitting_mode == 'point2plane':
            raise ValueError('point2plane fitting mode not implemented yet.')
        else:
            raise ValueError('Unknown fitting mode: ' + self.deform_fitting_mode)

        # Combined loss
        return self.output_loss + self.reg_loss

    def accuracy(self, outputs, labels):
        """
        Computes accuracy of the current batch
        :param outputs: logits predicted by the network
        :param labels: labels
        :return: accuracy value
        """

        # Set all ignored labels to -1 and correct the other label to be in [0, C-1] range
        target = - torch.ones_like(labels)
        for i, c in enumerate(self.valid_labels):
            target[labels == c] = i

        predicted = torch.argmax(outputs.data, dim=1)
        total = target.size(0)
        correct = (predicted == target).sum().item()

        return correct / total
