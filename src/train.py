#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clustering for historical data validation.

Author:
    Erik Johannes Husom

Created:
    2021-11-29 Monday 12:05:02

"""
import json
import sys

import numpy as np
import pandas as pd
import yaml
from joblib import dump
from sklearn.cluster import (
    DBSCAN,
    OPTICS,
    AffinityPropagation,
    AgglomerativeClustering,
    Birch,
    KMeans,
    MeanShift,
    MiniBatchKMeans,
)

from annotations import *
from config import *
from preprocess_utils import find_files, move_column


def train(dir_path=""):

    with open("params.yaml", "r") as params_file:
        params = yaml.safe_load(params_file)

    learning_method = params["cluster"]["learning_method"]
    n_clusters = params["cluster"]["n_clusters"]
    max_iter = params["cluster"]["max_iter"]
    use_predefined_centroids = params["cluster"]["use_predefined_centroids"]
    fix_predefined_centroids = params["cluster"]["fix_predefined_centroids"]
    annotations_dir = params["cluster"]["annotations_dir"]

    # Find data files and load feature_vectors.
    filepaths = find_files(dir_path, file_extension=".npy")
    feature_vectors = np.load(filepaths[0])

    model = build_model(learning_method, n_clusters, max_iter)

    if use_predefined_centroids:
        try:
            annotations_data_filepath = find_files(
                ANNOTATIONS_PATH / annotations_dir, file_extension=".csv"
            )[0]
        except:
            raise FileNotFoundError(
                "Annotation data not found. Cannot create predefined clusters without annotation data."
            )

        try:
            annotations_filepath = find_files(
                ANNOTATIONS_PATH / annotations_dir, file_extension=".json"
            )[0]
        except:
            raise FileNotFoundError(
                "Annotations not found. Cannot create predefined clusters without annotations."
            )

        annotation_data = pd.read_csv(annotations_data_filepath, index_col=0)
        annotations = read_annotations(annotations_filepath)
        predefined_centroids_dict = create_cluster_centers_from_annotations(
            annotation_data, annotations
        )

        with open(PREDEFINED_CENTROIDS_PATH, "w") as f:
            json.dump(predefined_centroids_dict, f)

        labels, model = fit_predict_with_predefined_centroids(
            feature_vectors,
            model,
            learning_method,
            n_clusters,
            predefined_centroids_dict,
            fix_predefined_centroids,
            max_iter=max_iter,
        )
    else:
        # TODO: Might consider iterating through damping values for
        # AffinityPropagation to increase chances of convergence.
        # if learning_method == "affinitypropagation":
        #     current_n_clusters = 0
        #     damping = 0.5
        #     while damping =< 1.0:
        #         model = AffinityPropagation(damping=damping, max_iter=1000, verbose=True)
        #         labels, model = fit_predict(feature_vectors, model)
        #         if C
        # else:
        labels, model = fit_predict(feature_vectors, model)

    unique_labels = np.unique(labels)

    # These lines will remove the noise cluster of DBSCAN
    # if unique_labels[0] == -1:
    #     unique_labels = unique_labels[1:]

    n_clusters = len(unique_labels)
    params["cluster"]["n_clusters"] = n_clusters

    # TODO: Not sure if it is a good idea to rewrite params.yaml during
    # execution of the pipeline.
    with open("params.yaml", "w") as params_file:
        yaml.dump(params, params_file)

    # If the model does not calculate its own cluster centers, do the
    # computation manually based on core samples or similar. Applies for the
    # following clustering algorithms:
    # - DBSCAN
    try:
        cluster_centers = model.cluster_centers_
    except:
        cluster_centers = []
        for c in unique_labels:
            current_label_feature_vectors = []

            # Find the indeces of the samples to use for computing cluster
            # centers. For models with core samples, for example DBSCAN, these
            # will be used. Other wise all samples in each cluster will be
            # used. The cluster centers will be the average of these samples
            # (either core samples or all samples).
            try:
                samples_indeces = model.core_sample_indices_
            except:
                samples_indeces = np.arange(feature_vectors.shape[0])

            for i in samples_indeces:
                if labels[i] == c:
                    current_label_feature_vectors.append(feature_vectors[i])

            if current_label_feature_vectors:
                # Convert to array
                current_label_feature_vectors = np.array(current_label_feature_vectors)
                # Take the average features of the core samples
                average_feature_vector = np.average(
                    current_label_feature_vectors, axis=0
                )
                # Add to the cluster centers
                cluster_centers.append(average_feature_vector)

            else:
                # If a cluster contains no samples, add an empty cluster center
                cluster_centers.append(np.zeros(feature_vectors.shape[-1]) * 0)
                # np.nan)

        cluster_centers = np.array(cluster_centers)

    assert n_clusters == cluster_centers.shape[0]

    # Clustering algorithms like AffinityPropagation might fail to converge,
    # so MiniBatchKMeans serves as a fallback method.
    if n_clusters == 0:
        print("Clustering failed to converge; falling back to MiniBatchKMeans.")
        model = MiniBatchKMeans(n_clusters=n_clusters, max_iter=max_iter)
        labels, model = fit_predict(feature_vectors, model)

    # Save output to disk
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODELS_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    dump(model, MODELS_FILE_PATH)
    pd.DataFrame(labels).to_csv(LABELS_PATH)
    pd.DataFrame(cluster_centers).to_csv(CLUSTER_CENTERS_PATH)


def build_model(learning_method, n_clusters, max_iter):
    """Build clustering model.

    Args:
        n_clusters (int): Number of clusters.
        max_iter (int): Maximum iterations.

    Returns:
        model: sklearn clustering model.

    """

    if learning_method == "meanshift":
        model = MeanShift()
    elif learning_method == "minibatchkmeans":
        model = MiniBatchKMeans(n_clusters=n_clusters, max_iter=max_iter)
    elif learning_method == "affinitypropagation":
        model = AffinityPropagation(damping=0.9, max_iter=1000, verbose=True)
    # TODO: To make DBSCAN work, we need to manually compute cluster centroids
    # (at least if we want to support the deviation metric), or we have to
    # remove dependence on cluster centroids being defined for any model.
    elif learning_method == "dbscan":
        model = DBSCAN()
    else:
        raise NotImplementedError(f"Learning method {learning_method} not implemented.")

    # model = DBSCAN(eps=0.30, min_samples=3)
    # model = GaussianMixture(n_components=1)

    return model


def fit_predict(feature_vectors, model):

    labels = model.fit_predict(feature_vectors)

    return labels, model


def fit_predict_with_predefined_centroids(
    feature_vectors,
    model,
    learning_method,
    n_clusters,
    predefined_centroids_dict,
    fix_predefined_centroids=False,
    max_iter=100,
):
    """Fit a model with fixe cluster centroids.

    Args:
        predefined_centroids_dict (dict): A dictionary containing predefined
            clusters, where the keys are the names of each cluster, and the
            values are an array containing the cluster centroids.

    Returns:

    """

    n_predefined_centroids = len(predefined_centroids_dict)
    predefined_centroids = []

    # Get predefined centroids from dictionary to array.
    for key in predefined_centroids_dict:
        predefined_centroids.append(predefined_centroids_dict[key])

    predefined_centroids = np.array(predefined_centroids)

    # If the number of predefined clusters is greater than the parameter
    # n_clusters, the former will override the latter.
    if n_clusters <= predefined_centroids.shape[0]:

        if n_clusters != predefined_centroids.shape[0]:
            n_clusters = predefined_centroids.shape[0]
            print(
                f"""Number of clusters changed from {n_clusters} to
            {predefined_centroids.shape[0]} in order to match the
            number of predefined clusters."""
            )

        # If the predefined centroids should be fixed, simply use the
        # predefined centroids as the model's cluster centers.
        if fix_predefined_centroids:
            print("Using fix_predefined_centroids=True, clustering is skipped.")
            model = MiniBatchKMeans(max_iter=1, n_clusters=n_clusters)
            model.fit(feature_vectors)
            model.cluster_centers_ = predefined_centroids
            labels = model.predict(feature_vectors)
        else:
            if learning_method == "meanshift":
                model = MeanShift(seeds=predefined_centroids)
            elif learning_method == "minibatchkmeans":
                model = MiniBatchKMeans(
                    max_iter=max_iter, n_clusters=n_clusters, init=predefined_centroids
                )
            else:
                print(
                    f"Cannot use predefined centroids with learning method {learning_method}. Falling back to MiniBatchKMeans."
                )
                model = MiniBatchKMeans(
                    max_iter=max_iter, n_clusters=n_clusters, init=predefined_centroids
                )

            labels = model.fit_predict(feature_vectors)

        return labels, model

    # If the number of predefined clusters is less than the parameter
    # n_clusters, we need some extra random centroids.
    elif predefined_centroids.shape[0] < n_clusters:

        # Run one iteration of clustering to obtain initial centroids.
        model = MiniBatchKMeans(max_iter=1, n_clusters=n_clusters)
        model.fit(feature_vectors)
        initial_centroids = model.cluster_centers_

        # Overwrite some of the initial centroids with the predefined ones.
        initial_centroids[0 : predefined_centroids.shape[0], :] = predefined_centroids

        if fix_predefined_centroids:
            current_centroids = initial_centroids

            for i in range(max_iter):
                model = MiniBatchKMeans(
                    max_iter=1, n_clusters=n_clusters, init=current_centroids
                )

                model.fit(feature_vectors)
                current_centroids = model.cluster_centers_

                # Overwrite some of the current centroids with the predefined ones.
                current_centroids[
                    0 : predefined_centroids.shape[0], :
                ] = predefined_centroids

            labels = model.predict(feature_vectors)

        else:
            if learning_method == "meanshift":
                model = MeanShift(seeds=initial_centroids)
            elif learning_method == "minibatchkmeans":
                model = MiniBatchKMeans(
                    max_iter=max_iter, n_clusters=n_clusters, init=initial_centroids
                )
            else:
                print(
                    f"Cannot use predefined centroids with learning method {learning_method}. Falling back to MiniBatchKMeans."
                )
                model = MiniBatchKMeans(
                    max_iter=max_iter, n_clusters=n_clusters, init=predefined_centroids
                )

            labels = model.fit_predict(feature_vectors)

        return labels, model


def predict(feature_vectors, model):
    labels = model.predict(feature_vectors)

    return labels


if __name__ == "__main__":

    train(sys.argv[1])
