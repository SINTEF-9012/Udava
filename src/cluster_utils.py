#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilities related to clustering and post-processing.

Author:
    Erik Johannes Husom

Created:
    2023-03-08 onsdag 09:09:52 

"""
import numpy as np
import pandas as pd

from sklearn.metrics import (
    calinski_harabasz_score,
    davies_bouldin_score,
    euclidean_distances,
    silhouette_score,
)

from config import *

def filter_segments(labels, min_segment_length, distances_to_centers=None):

    # Array for storing updated labels after short segments are filtered out.
    new_labels = labels.copy()

    segments = find_segments(labels)

    segments_sorted_on_length = segments[segments[:, 2].argsort()]

    shortest_segment = np.min(segments[:, 2])
    number_of_segments = len(segments)

    # Filter out the segments which are too short
    while shortest_segment < min_segment_length:

        # Get the information of current segment
        current_segment = segments_sorted_on_length[0]
        segment_idx = current_segment[0]
        label = current_segment[1]
        length = current_segment[2]
        start_idx = current_segment[3]
        end_idx = current_segment[4]

        # If the segment length is long enough, break the loop
        if length >= min_segment_length:
            break

        current_distances = distances_to_centers[start_idx : end_idx + 1, :]

        # Set the original smallest distance to be above the maximum, in order
        # to find the second closest cluster center
        current_distances[:, label] = np.max(current_distances) + 1

        # Find the second closest cluster center of the current data points
        second_closest_cluster_centers = current_distances.argmin(axis=1)

        # Find the most frequent second closest cluster center in the segment
        counts = np.bincount(second_closest_cluster_centers)
        most_frequent_second_closest_cluster_center = np.argmax(counts)
        current_new_labels = (
            np.ones_like(second_closest_cluster_centers)
            * most_frequent_second_closest_cluster_center
        )

        # Find the neighboring segment labels
        if segment_idx == 0:
            # If it is the first segment, then the label of the previous
            # segment will be set to equal the one for the next segment
            label_of_previous_segment = segments[segment_idx + 1][1]
            label_of_next_segment = segments[segment_idx + 1][1]
        elif segment_idx == len(segments) - 1:
            # If it is the last segment, then the label of the next
            # segment will be set to equal the one for the previous segment
            label_of_previous_segment = segments[segment_idx - 1][1]
            label_of_next_segment = segments[segment_idx - 1][1]
        else:
            label_of_previous_segment = segments[segment_idx - 1][1]
            label_of_next_segment = segments[segment_idx + 1][1]

        # If the most frequent second closest cluster center in the segment is
        # different from the previous and next segment, the current segment
        # will be split in half, and each half will be "swallowed" by the
        # neighboring segments. Otherwise the label is set to either the
        # previous or next segment label.
        if most_frequent_second_closest_cluster_center == label_of_previous_segment:
            current_new_labels[:] = label_of_previous_segment
        elif most_frequent_second_closest_cluster_center == label_of_next_segment:
            current_new_labels[:] = label_of_next_segment
        else:
            current_new_labels[: length // 2] = label_of_previous_segment
            current_new_labels[length // 2 :] = label_of_next_segment

        # Update with new labels
        new_labels[start_idx : end_idx + 1] = current_new_labels

        # Recompute segments, since they now have changed
        segments = find_segments(new_labels)
        segments_sorted_on_length = segments[segments[:, 2].argsort()]
        shortest_segment = np.min(segments[:, 2])

        if len(segments) == number_of_segments:
            print("Could not remove any more segments.")
            break

        number_of_segments = len(segments)

    return new_labels


def create_event_log_from_segments(segments):

    events = []
    feature_vector_timestamps = np.load(OUTPUT_PATH / "feature_vector_timestamps.npy")

    for i in range(len(segments)):

        current_segment = segments[i, :]
        label = current_segment[1]
        start_timestamp = feature_vector_timestamps[current_segment[3]]
        stop_timestamp = feature_vector_timestamps[current_segment[4]]

        events.append([start_timestamp, label, "started"])
        events.append([stop_timestamp, label, "completed"])

    event_log = pd.DataFrame(events, columns=["timestamp", "label", "status"])

    return event_log

def calculate_model_metrics(model, feature_vectors, labels):
    """Evaluate the cluster model.

    Silhouette score: Bounded between -1 for incorrect clustering and +1 for
        highly dense clustering. Scores around zero indicate overlapping clusters.
    Calinski-Harabasz Index: Higher when clusters are dense and well separated.
    Davies-Bouldin Index: Zero is the lowest score. Lower scores indicate a
        better partition.

    """

    silhouette = silhouette_score(feature_vectors, labels)
    chs = calinski_harabasz_score(feature_vectors, labels)
    dbs = davies_bouldin_score(feature_vectors, labels)

    metrics = {
        "silhouette_score": silhouette,
        "calinski_harabasz_score": chs,
        "davies_bouldin_score": dbs,
    }

    return metrics


def calculate_distances(feature_vectors, model, cluster_centers):

    distances_to_centers = euclidean_distances(feature_vectors, cluster_centers)
    sum_distance_to_centers = distances_to_centers.sum(axis=1)

    return distances_to_centers, sum_distance_to_centers


def find_segments(labels):
    """Find segments in array of labels.

    By segments we mean a continuous sequence of the same label.

    Args:
        labels (1d array): Array of labels.

    Returns:
        segments (2d array): Array of segments.

    Example:
        Let's say the array of labels looks like this:

        [0, 0, 1, 1, 1, 0, 0, 0, 0, 2, 2, 2]

        In this example we have four segments:

        1. Two zeros: [0, 0]
        2. Three ones: [1, 1, 1]
        3. Four zeros: [0, 0, 0, 0]
        4. Three twos: [2, 2, 2]

        The array `segments` has the following format:

        [segment_index, label, segment_length, start_index, end_index]

        `start_index` and `end_index` are indeces of the `labels` array.
        In this example it will then return the following:

        [[0, 0, 2, 0, 1],
         [1, 1, 3, 2, 4],
         [2, 0, 4, 5, 8],
         [3, 2, 3, 9, 11]]


    """

    segments = []

    current_label = labels[0]
    current_length = 1
    start_idx = 0
    segment_idx = 0

    # Count the length of each segment
    for i in range(1, len(labels)):
        if labels[i] == current_label:
            current_length += 1
            if i == len(labels) - 1:
                end_idx = i
                segments.append(
                    [segment_idx, current_label, current_length, start_idx, end_idx]
                )
        else:
            end_idx = i - 1
            segments.append(
                [segment_idx, current_label, current_length, start_idx, end_idx]
            )
            segment_idx += 1
            current_label = labels[i]
            current_length = 1
            start_idx = i

    return np.array(segments)


def create_event_log(labels, identifier=""):

    if identifier == "":
        identifier = str(uuid.uuid4())

    segments = find_segments(labels)
    event_log = create_event_log_from_segments(labels)
    event_log["case"] = identifier

    return event_log

def post_process_labels(
        model,
        cluster_centers,
        feature_vectors,
        labels,
        identifier,
        min_segment_length=0,
    ):

    if min_segment_length > 0:
        distances_to_centers, sum_distance_to_centers = calculate_distances(
            feature_vectors, model, cluster_centers
        )
        labels = filter_segments(labels, min_segment_length, distances_to_centers)

    event_log = create_event_log(labels, identifier=identifier)

    return labels, event_log
